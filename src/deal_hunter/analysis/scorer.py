"""Deal scorer: combines heuristic pricing with red flag analysis."""

from __future__ import annotations

import logging
import re

from deal_hunter.analysis.normalizer import HardwareMatch, HardwareNormalizer
from deal_hunter.analysis.pricing import (
    calculate_age_months,
    estimate_fair_value,
    price_vs_fair_pct,
)
from deal_hunter.analysis.red_flags import detect_red_flags
from deal_hunter.analysis.schemas import DealAnalysis

logger = logging.getLogger(__name__)

# Price extraction patterns for INR
_PRICE_PATTERNS = [
    re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+)", re.IGNORECASE),
    re.compile(r"([\d,]+)\s*(?:rs\.?|inr|₹)", re.IGNORECASE),
    re.compile(r"(?:price|asking|expected)\s*[:=\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+)", re.IGNORECASE),
]


def extract_price(text: str) -> int | None:
    """Extract the first INR price from text. Returns None if not found."""
    for pattern in _PRICE_PATTERNS:
        match = pattern.search(text)
        if match:
            price_str = match.group(1).replace(",", "")
            try:
                price = int(price_str)
                # Sanity: ignore numbers that are clearly not prices
                if 500 <= price <= 5_000_000:
                    return price
            except ValueError:
                continue
    return None


def _compute_deal_score(pct: float, flag_count: int, critical_flags: int) -> int:
    """Compute a 1-10 deal score from price deviation and red flags.

    pct < 0 means below fair (good for buyer).
    """
    if critical_flags > 0:
        return 1  # any critical flag = likely scam

    # Base score from price: -30% below fair -> 10, at fair -> 6, +30% above -> 2
    if pct <= -30:
        base = 10
    elif pct <= -15:
        base = 8
    elif pct <= -5:
        base = 7
    elif pct <= 5:
        base = 6
    elif pct <= 15:
        base = 5
    elif pct <= 30:
        base = 4
    else:
        base = 2

    # Deduct for non-critical flags
    penalty = min(flag_count * 0.5, 3)
    return max(1, min(10, round(base - penalty)))


def _compute_verdict(score: int) -> str:
    if score >= 8:
        return "BUY"
    if score >= 6:
        return "NEGOTIATE"
    if score >= 3:
        return "PASS"
    return "SCAM_RISK"


def _suggest_offer(asking: int, fair_mid: int, verdict: str) -> int | None:
    """Suggest a counter-offer for NEGOTIATE verdicts."""
    if verdict != "NEGOTIATE":
        return None
    # Suggest midpoint between asking and fair, biased toward fair
    return round((asking + fair_mid * 2) / 3)


def _build_analysis(
    hw: HardwareMatch,
    price: int,
    location: str,
    description: str,
    normalizer: HardwareNormalizer,
) -> DealAnalysis:
    """Build a DealAnalysis from identified hardware and price."""
    age = calculate_age_months(hw.release_date)
    fair = estimate_fair_value(hw.msrp_inr, age, hw.category)
    pct = price_vs_fair_pct(price, fair)

    full_text = f"{hw.canonical_name} {description}".strip()
    flags = detect_red_flags(
        hw=hw,
        fair=fair,
        asking_price=price,
        description=full_text,
        location=location,
        mining_popular_ids=normalizer.mining_popular_ids,
    )

    critical_count = sum(1 for f in flags if f.severity == "critical")
    score = _compute_deal_score(pct, len(flags), critical_count)
    verdict = _compute_verdict(score)

    gen_str = f" ({hw.generation})" if hw.generation else ""
    reasoning_parts = [f"{hw.canonical_name}{gen_str}, ~{age} months old."]
    reasoning_parts.append(f"Fair range: ₹{fair.low:,} – ₹{fair.high:,} (mid ₹{fair.midpoint:,}).")
    if pct < -10:
        reasoning_parts.append(f"Asking ₹{price:,} is {abs(pct):.0f}% below fair — good value.")
    elif pct > 10:
        reasoning_parts.append(f"Asking ₹{price:,} is {pct:.0f}% above fair — overpriced.")
    else:
        reasoning_parts.append(f"Asking ₹{price:,} is within fair range.")
    if flags:
        reasoning_parts.append(f"{len(flags)} red flag(s) detected.")

    return DealAnalysis(
        canonical_name=hw.canonical_name,
        category=hw.category,
        brand=hw.brand,
        generation=hw.generation,
        asking_price=price,
        fair_market_low=fair.low,
        fair_market_high=fair.high,
        fair_market_mid=fair.midpoint,
        msrp=fair.msrp,
        price_vs_fair_pct=pct,
        deal_score=score,
        verdict=verdict,
        reasoning=" ".join(reasoning_parts),
        red_flags=flags,
        confidence=hw.confidence,
        suggested_offer=_suggest_offer(price, fair.midpoint, verdict),
        age_months=age,
        depreciation_pct=fair.depreciation_pct,
    )


def _resolve_hw_and_price(
    text: str,
    asking_price: int | None,
    description: str,
    normalizer: HardwareNormalizer,
) -> tuple[HardwareMatch | None, int | None]:
    """Resolve hardware identity (local only) and price."""
    hw = normalizer.normalize(text)
    if hw is None and description:
        hw = normalizer.normalize(description)

    price = asking_price
    if price is None:
        price = extract_price(text)
    if price is None and description:
        price = extract_price(description)

    return hw, price


def analyze_deal(
    text: str,
    asking_price: int | None = None,
    location: str = "",
    description: str = "",
    normalizer: HardwareNormalizer | None = None,
    ai_api_key: str = "",
) -> DealAnalysis | None:
    """Analyze a listing synchronously. Uses local normalizer only.

    For AI-powered analysis of unknown products, use analyze_deal_async.
    The ai_api_key param is kept for backward compat but ignored here.
    """
    nrm = normalizer or HardwareNormalizer()
    hw, price = _resolve_hw_and_price(text, asking_price, description, nrm)

    if hw is None:
        logger.debug("Local normalizer miss: %s", text[:80])
        return None
    if hw.msrp_inr <= 0 or price is None:
        return None

    return _build_analysis(hw, price, location, description, nrm)


async def analyze_deal_async(
    text: str,
    asking_price: int | None = None,
    location: str = "",
    description: str = "",
    normalizer: HardwareNormalizer | None = None,
    ai_api_key: str = "",
) -> DealAnalysis | None:
    """Analyze a listing with AI fallback for unknown products."""
    nrm = normalizer or HardwareNormalizer()
    hw, price = _resolve_hw_and_price(text, asking_price, description, nrm)

    # AI fallback for unrecognized products
    if hw is None and ai_api_key:
        from deal_hunter.analysis.ai_normalizer import ai_normalize

        hw = await ai_normalize(text, description, api_key=ai_api_key)

    if hw is None:
        logger.info("Could not identify hardware from: %s", text[:80])
        return None
    if hw.msrp_inr <= 0:
        logger.info("No MSRP available for: %s", hw.canonical_name)
        return None
    if price is None:
        logger.info("Could not extract price from: %s", text[:80])
        return None

    return _build_analysis(hw, price, location, description, nrm)
