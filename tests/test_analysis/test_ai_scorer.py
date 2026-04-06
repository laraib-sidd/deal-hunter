"""Tests for AI deal scorer (Groq)."""

from __future__ import annotations

import json

import pytest

from deal_hunter.analysis.ai_scorer import score_with_ai
from deal_hunter.analysis.normalizer import HardwareMatch
from deal_hunter.analysis.pricing import FairValueEstimate

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _groq_response(content: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


@pytest.fixture
def sample_hw() -> HardwareMatch:
    return HardwareMatch(
        hardware_id="nvidia-rtx-3060",
        canonical_name="NVIDIA GeForce RTX 3060",
        category="gpu",
        brand="NVIDIA",
        generation="Ampere",
        msrp_inr=29500,
        release_date="2021-02",
        confidence=0.95,
        specs={"vram_gb": 12},
    )


@pytest.fixture
def sample_fair() -> FairValueEstimate:
    return FairValueEstimate(
        midpoint=10000,
        low=8500,
        high=11500,
        msrp=29500,
        age_months=62,
        depreciation_pct=0.66,
    )


@pytest.mark.asyncio
async def test_ai_scorer_parses_response(httpx_mock, sample_hw, sample_fair) -> None:
    ai_response = {
        "deal_score": 8,
        "verdict": "BUY",
        "reasoning": "RTX 3060 at 12k is a solid deal for Indian market.",
        "fair_market_low": 12000,
        "fair_market_high": 17000,
        "red_flags": [],
        "suggested_offer": None,
    }
    httpx_mock.add_response(url=GROQ_URL, json=_groq_response(ai_response))

    result = await score_with_ai(
        title="RTX 3060 12GB",
        asking_price=12000,
        hw=sample_hw,
        fair=sample_fair,
        api_key="test-key",
    )

    assert result is not None
    assert result.deal_score == 8
    assert result.verdict == "BUY"
    assert result.fair_market_low == 12000
    assert result.fair_market_high == 17000


@pytest.mark.asyncio
async def test_ai_scorer_handles_red_flags(httpx_mock, sample_hw, sample_fair) -> None:
    ai_response = {
        "deal_score": 3,
        "verdict": "PASS",
        "reasoning": "Ex-mining card, avoid.",
        "fair_market_low": 8000,
        "fair_market_high": 12000,
        "red_flags": [
            {"flag_type": "mining_wear", "severity": "high", "detail": "Likely ex-mining GPU"}
        ],
        "suggested_offer": None,
    }
    httpx_mock.add_response(url=GROQ_URL, json=_groq_response(ai_response))

    result = await score_with_ai(
        title="RTX 3060 12GB",
        asking_price=12000,
        hw=sample_hw,
        fair=sample_fair,
        description="Used in mining rig 24/7",
        api_key="test-key",
    )

    assert result is not None
    assert result.deal_score == 3
    assert len(result.red_flags) == 1
    assert result.red_flags[0].flag_type == "mining_wear"


@pytest.mark.asyncio
async def test_ai_scorer_no_api_key_returns_none(sample_hw, sample_fair) -> None:
    result = await score_with_ai(
        title="RTX 3060",
        asking_price=12000,
        hw=sample_hw,
        fair=sample_fair,
        api_key="",
    )
    assert result is None


@pytest.mark.asyncio
async def test_ai_scorer_handles_api_error(httpx_mock, sample_hw, sample_fair) -> None:
    httpx_mock.add_response(url=GROQ_URL, status_code=500, text="Internal Server Error")

    result = await score_with_ai(
        title="RTX 3060",
        asking_price=12000,
        hw=sample_hw,
        fair=sample_fair,
        api_key="test-key",
    )
    assert result is None
