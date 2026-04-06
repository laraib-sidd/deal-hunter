"""Rule-based red flag detection for hardware listings."""

from __future__ import annotations

import re

from deal_hunter.analysis.normalizer import HardwareMatch
from deal_hunter.analysis.pricing import FairValueEstimate
from deal_hunter.analysis.schemas import RedFlag

# Keywords that suggest crypto mining usage
_MINING_KEYWORDS = re.compile(
    r"\b(?:mining|mined|crypto|ethereum|eth|hashrate|24/7|server\s+use|rig)\b",
    re.IGNORECASE,
)

# Pressure language suggesting urgency or scam
_PRESSURE_KEYWORDS = re.compile(
    r"\b(?:selling\s+today|urgent\s+sale|many\s+buyers|first\s+come|dm\s+fast|quick\s+sale)\b",
    re.IGNORECASE,
)

# Multiple units suggest bulk seller / miner offloading
_BULK_KEYWORDS = re.compile(
    r"\b(?:(\d+)\s*(?:pieces|pcs|units|nos|available)|bulk)\b",
    re.IGNORECASE,
)


def detect_red_flags(
    hw: HardwareMatch,
    fair: FairValueEstimate,
    asking_price: float,
    description: str = "",
    location: str = "",
    mining_popular_ids: list[str] | None = None,
) -> list[RedFlag]:
    """Run all rule-based red flag checks. Returns list of detected flags."""
    flags: list[RedFlag] = []

    # 1. Suspicious pricing (too cheap)
    if asking_price < fair.low * 0.65:
        pct_below = round((1 - asking_price / fair.midpoint) * 100)
        flags.append(RedFlag(
            flag_type="suspicious_price",
            severity="critical",
            detail=f"Price is {pct_below}% below fair market — possible scam or defective unit",
        ))
    elif asking_price < fair.low * 0.80:
        pct_below = round((1 - asking_price / fair.midpoint) * 100)
        flags.append(RedFlag(
            flag_type="below_market",
            severity="medium",
            detail=f"Price is {pct_below}% below fair market — investigate condition carefully",
        ))

    # 2. Overpriced
    if asking_price > fair.high * 1.20:
        pct_above = round((asking_price / fair.midpoint - 1) * 100)
        flags.append(RedFlag(
            flag_type="overpriced",
            severity="medium",
            detail=f"Price is {pct_above}% above fair market — room to negotiate",
        ))

    # 3. Mining risk (GPU-specific)
    mining_ids = mining_popular_ids or []
    if hw.hardware_id in mining_ids:
        flags.append(RedFlag(
            flag_type="mining_popular_model",
            severity="medium",
            detail=f"{hw.canonical_name} was popular for crypto mining — check for wear signs",
        ))

    if _MINING_KEYWORDS.search(description):
        flags.append(RedFlag(
            flag_type="mining_keywords",
            severity="high",
            detail="Description contains mining-related keywords — likely ex-mining hardware",
        ))

    # 4. Pressure language
    if _PRESSURE_KEYWORDS.search(description):
        flags.append(RedFlag(
            flag_type="pressure_language",
            severity="medium",
            detail="Listing uses urgency/pressure language — take your time, don't rush",
        ))

    # 5. Bulk seller
    bulk_match = _BULK_KEYWORDS.search(description)
    if bulk_match:
        flags.append(RedFlag(
            flag_type="bulk_seller",
            severity="high",
            detail="Seller has multiple units — could be offloading mining/corporate hardware",
        ))

    # 6. Very old hardware (>5 years)
    if fair.age_months > 60:
        flags.append(RedFlag(
            flag_type="very_old",
            severity="low",
            detail=f"Hardware is {fair.age_months // 12}+ years old — expect limited remaining lifespan",
        ))

    # 7. Missing warranty indicators
    desc_lower = description.lower()
    if description and "warranty" not in desc_lower and "invoice" not in desc_lower and "bill" not in desc_lower:
        flags.append(RedFlag(
            flag_type="missing_warranty_info",
            severity="low",
            detail="No mention of warranty or invoice — ask seller about warranty transferability",
        ))

    return flags
