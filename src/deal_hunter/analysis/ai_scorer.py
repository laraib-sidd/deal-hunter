"""AI-powered deal scoring using Groq (free tier, Llama 4 Scout)."""

from __future__ import annotations

import json
import logging

import httpx

from deal_hunter.analysis.normalizer import HardwareMatch
from deal_hunter.analysis.pricing import FairValueEstimate
from deal_hunter.analysis.schemas import DealAnalysis, RedFlag

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

SYSTEM_PROMPT = """You are a used hardware pricing expert for the Indian market.
You analyze second-hand hardware listings and assess whether they are good deals.

You know:
- Indian used hardware market prices (OLX, TechEnclave, Reddit r/IndianGaming)
- Depreciation curves for GPUs, CPUs, RAM, SSDs, monitors
- Red flags: ex-mining GPUs, scam patterns, overpriced listings
- City tier pricing differences (Mumbai/Delhi higher than tier-2)
- Warranty transferability rules in India
- Festival season pricing patterns

Always respond with valid JSON. Be conservative —
only rate a deal 8+ if it's genuinely significantly below market."""

ANALYSIS_PROMPT = """Analyze this used hardware listing from the Indian market.

LISTING:
- Title: {title}
- Asking Price: ₹{asking_price:,}
- Location: {location}
- Description: {description}
- Source: {source}

REFERENCE DATA (from our depreciation model):
- Identified as: {canonical_name} ({generation})
- Category: {category}
- Original MSRP: ₹{msrp:,}
- Model age: ~{age_months} months
- Our estimated fair range: ₹{fair_low:,} – ₹{fair_high:,} (mid ₹{fair_mid:,})
- Our depreciation estimate: {depreciation_pct:.0%}

NOTE: Our depreciation model may undervalue hardware that is still relevant for
current gaming/workloads. Use your knowledge of actual Indian market prices to
override our estimates where appropriate.

Return JSON with these fields:
- deal_score: 1-10 integer
- verdict: one of BUY, NEGOTIATE, PASS, SCAM_RISK
- reasoning: 2-3 sentence explanation
- fair_market_low: int (your estimate in INR)
- fair_market_high: int (your estimate in INR)
- red_flags: array of objects with flag_type, severity (low/medium/high/critical), detail
- suggested_offer: int or null (INR counter-offer if NEGOTIATE)"""


async def score_with_ai(
    title: str,
    asking_price: int,
    hw: HardwareMatch,
    fair: FairValueEstimate,
    description: str = "",
    location: str = "",
    source: str = "",
    api_key: str = "",
    model: str = DEFAULT_MODEL,
) -> DealAnalysis | None:
    """Score a deal using Groq. Returns enhanced DealAnalysis or None on failure."""
    if not api_key:
        logger.warning("No Groq API key configured — skipping AI scoring")
        return None

    prompt = ANALYSIS_PROMPT.format(
        title=title,
        asking_price=asking_price,
        location=location or "Unknown",
        description=description[:1500] or "No description",
        source=source,
        canonical_name=hw.canonical_name,
        generation=hw.generation,
        category=hw.category,
        msrp=hw.msrp_inr,
        age_months=fair.age_months,
        fair_low=fair.low,
        fair_high=fair.high,
        fair_mid=fair.midpoint,
        depreciation_pct=fair.depreciation_pct,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 500,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )

        if resp.status_code != 200:
            logger.error("Groq API returned %d: %s", resp.status_code, resp.text[:200])
            return None

        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # Groq JSON mode should give clean JSON, but handle edge cases
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        result = json.loads(content)

    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError) as exc:
        logger.error("AI scoring failed: %s", exc)
        return None

    # Build DealAnalysis from AI response
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
