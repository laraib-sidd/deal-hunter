"""AI-powered deal scoring using Groq (free tier, Llama 4 Scout)."""

from __future__ import annotations

import json
import logging

from deal_hunter.analysis.groq_client import extract_content, groq_chat
from deal_hunter.analysis.normalizer import HardwareMatch
from deal_hunter.analysis.pricing import FairValueEstimate
from deal_hunter.analysis.schemas import DealAnalysis, RedFlag

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a used hardware pricing expert for the Indian market.
You analyze second-hand hardware listings and assess whether they are good deals.

You know:
- Indian used hardware market prices (OLX, TechEnclave, Reddit r/IndianGaming)
- Depreciation curves for GPUs, CPUs, RAM, SSDs, monitors
- Red flags: ex-mining GPUs, scam patterns, overpriced listings
- City tier pricing differences (Mumbai/Delhi higher than tier-2)
- Warranty transferability rules in India

Always respond with valid JSON. Be conservative —
only rate a deal 8+ if it's genuinely significantly below market."""

ANALYSIS_PROMPT = """Analyze this used hardware listing from the Indian market.

LISTING:
- Title: {title}
- Asking Price: ₹{asking_price:,}
- Location: {location}
- Description: {description}
- Source: {source}

REFERENCE DATA:
- Identified as: {canonical_name} ({generation})
- Category: {category}
- Original MSRP: ₹{msrp:,}
- Model age: ~{age_months} months
- Our estimated fair range: ₹{fair_low:,} – ₹{fair_high:,} (mid ₹{fair_mid:,})

NOTE: Our depreciation model may undervalue still-relevant hardware.
Override with your knowledge of actual Indian market prices.

Return JSON:
- deal_score: 1-10 integer
- verdict: BUY, NEGOTIATE, PASS, or SCAM_RISK
- reasoning: 2-3 sentence explanation
- fair_market_low: int INR
- fair_market_high: int INR
- red_flags: array of {{flag_type, severity, detail}}
- suggested_offer: int or null"""


async def score_with_ai(
    title: str,
    asking_price: int,
    hw: HardwareMatch,
    fair: FairValueEstimate,
    description: str = "",
    location: str = "",
    source: str = "",
    api_key: str = "",
    model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
) -> DealAnalysis | None:
    """Score a deal using Groq. Returns enhanced DealAnalysis or None on failure."""
    if not api_key:
        return None

    prompt = ANALYSIS_PROMPT.format(
        title=title,
        asking_price=asking_price,
        location=location or "Unknown",
        description=description[:1500] or "No description",
        source=source,
        canonical_name=hw.canonical_name,
        generation=hw.generation or "Unknown",
        category=hw.category,
        msrp=hw.msrp_inr,
        age_months=fair.age_months,
        fair_low=fair.low,
        fair_high=fair.high,
        fair_mid=fair.midpoint,
    )

    try:
        response = await groq_chat(
            api_key=api_key,
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
        )
        if response is None:
            return None

        result = json.loads(extract_content(response))

    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.error("AI scoring failed: %s", exc)
        return None

    ai_flags = [
        RedFlag(
            flag_type=f.get("flag_type", "unknown"),
            severity=f.get("severity", "low"),
            detail=f.get("detail", ""),
        )
        for f in result.get("red_flags", [])
    ]

    ai_fair_low = result.get("fair_market_low", fair.low)
    ai_fair_high = result.get("fair_market_high", fair.high)
    ai_fair_mid = (ai_fair_low + ai_fair_high) // 2
    pct = round(((asking_price - ai_fair_mid) / ai_fair_mid) * 100, 1) if ai_fair_mid else 0.0

    return DealAnalysis(
        canonical_name=hw.canonical_name,
        category=hw.category,
        brand=hw.brand,
        generation=hw.generation,
        asking_price=asking_price,
        fair_market_low=ai_fair_low,
        fair_market_high=ai_fair_high,
        fair_market_mid=ai_fair_mid,
        msrp=hw.msrp_inr,
        price_vs_fair_pct=pct,
        deal_score=max(1, min(10, result.get("deal_score", 5))),
        verdict=result.get("verdict", "PASS"),
        reasoning=result.get("reasoning", "AI analysis completed."),
        red_flags=ai_flags,
        confidence=min(hw.confidence + 0.05, 1.0),
        suggested_offer=result.get("suggested_offer"),
        age_months=fair.age_months,
        depreciation_pct=fair.depreciation_pct,
    )
