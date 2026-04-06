"""AI fallback normalizer — uses Groq (free tier) when regex+fuzzy fails."""

from __future__ import annotations

import json
import logging

from deal_hunter.analysis.groq_client import extract_content, groq_chat
from deal_hunter.analysis.normalizer import HardwareMatch

logger = logging.getLogger(__name__)

PROMPT = """Identify this product from a second-hand listing in India.

Listing title: "{title}"
Description: "{description}"

Return a JSON object with these fields:
- canonical_name: full product name (e.g. "Crucial T700 4TB PCIe Gen5 NVMe SSD")
- category: one of gpu, cpu, ram, ssd, monitor, motherboard, psu, laptop, headphone, keyboard, mouse, case, networking, storage, peripheral, other
- brand: brand name
- generation: tech generation or series (e.g. "PCIe Gen5", "Zen 4", "Wi-Fi 6E")
- msrp_inr: estimated NEW retail price in India in INR (integer)
- release_year: YYYY or YYYY-MM if known

Use current Indian retail prices (Amazon.in/Flipkart). Be accurate with MSRP."""


async def ai_normalize(
    title: str,
    description: str = "",
    api_key: str = "",
    model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
) -> HardwareMatch | None:
    """Use Groq to identify unknown hardware. Returns HardwareMatch or None."""
    if not api_key:
        return None

    try:
        response = await groq_chat(
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": PROMPT.format(
                title=title[:200],
                description=description[:500],
            )}],
        )
        if response is None:
            return None

        parsed = json.loads(extract_content(response))
        # Groq sometimes wraps in a list
        result = parsed[0] if isinstance(parsed, list) else parsed
        if not isinstance(result, dict):
            return None

        release = result.get("release_year") or "2023"
        release = str(release).strip()
        if release.lower() in ("none", "null", "unknown", ""):
            release = "2023"
        if len(release) == 4:
            release = f"{release}-01"

        return HardwareMatch(
            hardware_id=f"ai-{result.get('category', 'other')}-{hash(title) & 0xFFFF:04x}",
            canonical_name=result.get("canonical_name") or title,
            category=result.get("category") or "other",
            brand=result.get("brand") or "Unknown",
            generation=result.get("generation") or "",
            msrp_inr=int(result.get("msrp_inr") or 0),
            release_date=str(release),
            confidence=0.75,
        )

    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.debug("AI normalize error: %s", exc)
        return None
