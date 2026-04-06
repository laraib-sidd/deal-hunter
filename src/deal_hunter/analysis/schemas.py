"""Pydantic models for deal analysis output."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RedFlag(BaseModel):
    """A single risk indicator on a listing."""

    flag_type: str  # e.g. "mining_risk", "suspicious_price", "missing_warranty"
    severity: str  # "low", "medium", "high", "critical"
    detail: str


class DealAnalysis(BaseModel):
    """Complete analysis of a hardware listing."""

    # Identification
    canonical_name: str
    category: str
    brand: str
    generation: str = ""

    # Pricing
    asking_price: int
    fair_market_low: int
    fair_market_high: int
    fair_market_mid: int
    msrp: int
    price_vs_fair_pct: float = Field(description="Negative = below fair (good deal)")

    # Scoring
    deal_score: int = Field(ge=1, le=10, description="1=terrible, 10=steal")
    verdict: str  # BUY, NEGOTIATE, PASS, SCAM_RISK
    reasoning: str

    # Risk
    red_flags: list[RedFlag] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    # Suggestion
    suggested_offer: int | None = None
    age_months: int = 0
    depreciation_pct: float = 0.0
