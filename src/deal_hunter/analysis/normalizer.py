"""Hardware name normalization: regex patterns -> fuzzy match -> unknown."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass(frozen=True)
class HardwareMatch:
    """Result of normalizing a hardware name."""

    hardware_id: str
    canonical_name: str
    category: str
    brand: str
    generation: str
    msrp_inr: int
    release_date: str
    confidence: float  # 0.0 - 1.0
    specs: dict = field(default_factory=dict)


# Pre-compiled regex patterns for common hardware naming conventions.
# Ordered most-specific first so "rtx 4070 ti super" matches before "rtx 4070".
_GPU_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:rtx\s*)?4090\b", re.IGNORECASE), "nvidia-rtx-4090"),
    (re.compile(r"\b(?:rtx\s*)?4080\s*super\b", re.IGNORECASE), "nvidia-rtx-4080-super"),
    (re.compile(r"\b(?:rtx\s*)?4080\b", re.IGNORECASE), "nvidia-rtx-4080"),
    (re.compile(r"\b(?:rtx\s*)?4070\s*ti\s*super\b", re.IGNORECASE), "nvidia-rtx-4070-ti-super"),
    (re.compile(r"\b(?:rtx\s*)?4070\s*ti\b", re.IGNORECASE), "nvidia-rtx-4070-ti"),
    (re.compile(r"\b(?:rtx\s*)?4070\s*super\b", re.IGNORECASE), "nvidia-rtx-4070-super"),
    (re.compile(r"\b(?:rtx\s*)?4070\b", re.IGNORECASE), "nvidia-rtx-4070"),
    (re.compile(r"\b(?:rtx\s*)?4060\s*ti\b", re.IGNORECASE), "nvidia-rtx-4060-ti"),
    (re.compile(r"\b(?:rtx\s*)?4060\b", re.IGNORECASE), "nvidia-rtx-4060"),
    (re.compile(r"\b(?:rtx\s*)?3090\b", re.IGNORECASE), "nvidia-rtx-3090"),
    (re.compile(r"\b(?:rtx\s*)?3080\s*ti\b", re.IGNORECASE), "nvidia-rtx-3080-ti"),
    (re.compile(r"\b(?:rtx\s*)?3080\b", re.IGNORECASE), "nvidia-rtx-3080"),
    (re.compile(r"\b(?:rtx\s*)?3070\s*ti\b", re.IGNORECASE), "nvidia-rtx-3070-ti"),
    (re.compile(r"\b(?:rtx\s*)?3070\b", re.IGNORECASE), "nvidia-rtx-3070"),
    (re.compile(r"\b(?:rtx\s*)?3060\s*ti\b", re.IGNORECASE), "nvidia-rtx-3060-ti"),
    (re.compile(r"\b(?:rtx\s*)?3060\b", re.IGNORECASE), "nvidia-rtx-3060"),
    (re.compile(r"\b(?:gtx\s*)?1660\s*super\b", re.IGNORECASE), "nvidia-gtx-1660-super"),
    (re.compile(r"\b(?:gtx\s*)?1650\b", re.IGNORECASE), "nvidia-gtx-1650"),
    (re.compile(r"\brx\s*7900\s*xtx\b", re.IGNORECASE), "amd-rx-7900-xtx"),
    (re.compile(r"\brx\s*7800\s*xt\b", re.IGNORECASE), "amd-rx-7800-xt"),
    (re.compile(r"\brx\s*7600\b", re.IGNORECASE), "amd-rx-7600"),
    (re.compile(r"\brx\s*6800\s*xt\b", re.IGNORECASE), "amd-rx-6800-xt"),
    (re.compile(r"\brx\s*6700\s*xt\b", re.IGNORECASE), "amd-rx-6700-xt"),
    (re.compile(r"\brx\s*580\b", re.IGNORECASE), "amd-rx-580"),
]

_CPU_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:ryzen\s*9\s*)?7950x\b", re.IGNORECASE), "amd-ryzen-9-7950x"),
    (re.compile(r"\b(?:ryzen\s*7\s*)?7800x3d\b", re.IGNORECASE), "amd-ryzen-7-7800x3d"),
    (re.compile(r"\b(?:ryzen\s*7\s*)?5800x\b", re.IGNORECASE), "amd-ryzen-7-5800x"),
    (re.compile(r"\b(?:ryzen\s*5\s*)?7600x\b", re.IGNORECASE), "amd-ryzen-5-7600x"),
    (re.compile(r"\b(?:ryzen\s*5\s*)?5600x\b", re.IGNORECASE), "amd-ryzen-5-5600x"),
    (re.compile(r"\b(?:ryzen\s*5\s*)?5600\b", re.IGNORECASE), "amd-ryzen-5-5600"),
    (re.compile(r"\b(?:ryzen\s*9\s*)?5900x\b", re.IGNORECASE), "amd-ryzen-9-5900x"),
    (re.compile(r"\bi[9\-]\s*14900k\b", re.IGNORECASE), "intel-i9-14900k"),
    (re.compile(r"\bi[7\-]\s*14700k\b", re.IGNORECASE), "intel-i7-14700k"),
    (re.compile(r"\bi[5\-]\s*14600k\b", re.IGNORECASE), "intel-i5-14600k"),
    (re.compile(r"\bi[5\-]\s*13400f\b", re.IGNORECASE), "intel-i5-13400f"),
    (re.compile(r"\bi[5\-]\s*12400f\b", re.IGNORECASE), "intel-i5-12400f"),
]


class HardwareNormalizer:
    """Normalizes messy listing titles to canonical hardware names."""

    def __init__(self, db_path: Path | None = None) -> None:
        path = db_path or (_DATA_DIR / "hardware_db.json")
        with open(path) as f:
            self._raw_db = json.load(f)

        # Build lookup: hardware_id -> entry dict
        self._entries: dict[str, dict] = {}
        # Build alias -> hardware_id mapping for fuzzy search
        self._alias_map: dict[str, str] = {}

        for category in ("gpu", "cpu", "ram", "ssd", "monitor", "motherboard", "psu"):
            for entry in self._raw_db.get(category, []):
                hw_id = entry["id"]
                self._entries[hw_id] = {**entry, "category": category}
                for alias in entry.get("aliases", []):
                    self._alias_map[alias.lower()] = hw_id

        self._alias_choices = list(self._alias_map.keys())
        logger.info("Loaded %d hardware entries, %d aliases", len(self._entries), len(self._alias_map))

    def normalize(self, text: str) -> HardwareMatch | None:
        """Try to identify hardware from free-text. Returns None if unrecognized."""
        text_lower = text.lower().strip()

        # Stage 1: Regex patterns (fast, high confidence)
        match = self._try_regex(text_lower)
        if match:
            return match

        # Stage 2: Fuzzy match against alias table
        match = self._try_fuzzy(text_lower)
        if match:
            return match

        logger.debug("Could not normalize: %s", text[:80])
        return None

    def _try_regex(self, text: str) -> HardwareMatch | None:
        for patterns in (_GPU_PATTERNS, _CPU_PATTERNS):
            for pattern, hw_id in patterns:
                if pattern.search(text):
                    return self._build_match(hw_id, confidence=0.95)
        return None

    def _try_fuzzy(self, text: str, threshold: int = 70) -> HardwareMatch | None:
        if not self._alias_choices:
            return None

        result = process.extractOne(text, self._alias_choices, scorer=fuzz.token_sort_ratio)
        if result is None:
            return None

        best_alias, score, _idx = result
        if score < threshold:
            return None

        hw_id = self._alias_map[best_alias]
        confidence = min(score / 100.0, 0.90)  # cap fuzzy at 0.90
        return self._build_match(hw_id, confidence=confidence)

    def _build_match(self, hw_id: str, confidence: float) -> HardwareMatch:
        entry = self._entries[hw_id]
        return HardwareMatch(
            hardware_id=hw_id,
            canonical_name=entry["name"],
            category=entry["category"],
            brand=entry["brand"],
            generation=entry["generation"],
            msrp_inr=entry["msrp_inr"],
            release_date=entry["release_date"],
            confidence=confidence,
            specs=entry.get("specs", {}),
        )

    def get_entry(self, hw_id: str) -> dict | None:
        """Direct lookup by hardware ID."""
        return self._entries.get(hw_id)

    @property
    def mining_popular_ids(self) -> list[str]:
        return self._raw_db.get("mining_popular_gpus", [])

    @property
    def city_tiers(self) -> dict[str, list[str]]:
        return self._raw_db.get("city_tiers", {})
