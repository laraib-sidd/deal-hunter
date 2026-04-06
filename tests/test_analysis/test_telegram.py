"""Tests for Telegram notification formatting and sending."""

from __future__ import annotations

import pytest

from deal_hunter.analysis.schemas import DealAnalysis, RedFlag
from deal_hunter.notifications.telegram import _format_deal_message, send_deal_alert


@pytest.fixture
def sample_analysis() -> DealAnalysis:
    return DealAnalysis(
        canonical_name="NVIDIA GeForce RTX 3060",
        category="gpu",
        brand="NVIDIA",
        generation="Ampere",
        asking_price=12000,
        fair_market_low=10000,
        fair_market_high=15000,
        fair_market_mid=12500,
        msrp=29500,
        price_vs_fair_pct=-4.0,
        deal_score=7,
        verdict="BUY",
        reasoning="Good deal for the Indian market.",
        red_flags=[],
        confidence=0.95,
        age_months=62,
        depreciation_pct=0.66,
    )


class TestMessageFormatting:
    def test_buy_message(self, sample_analysis: DealAnalysis) -> None:
        msg = _format_deal_message(sample_analysis)
        assert "BUY" in msg
        assert "RTX 3060" in msg
        assert "₹12,000" in msg

    def test_with_red_flags(self, sample_analysis: DealAnalysis) -> None:
        sample_analysis.red_flags = [
            RedFlag(flag_type="mining_risk", severity="high", detail="Ex-mining GPU")
        ]
        msg = _format_deal_message(sample_analysis)
        assert "Ex-mining GPU" in msg

    def test_with_url(self, sample_analysis: DealAnalysis) -> None:
        msg = _format_deal_message(sample_analysis, listing_url="https://example.com/listing")
        assert "https://example.com/listing" in msg


@pytest.mark.asyncio
async def test_send_skips_without_config(sample_analysis: DealAnalysis) -> None:
    result = await send_deal_alert(
        bot_token="",
        chat_id="",
        analysis=sample_analysis,
    )
    assert result is False


@pytest.mark.asyncio
async def test_send_success(httpx_mock, sample_analysis: DealAnalysis) -> None:
    httpx_mock.add_response(
        url="https://api.telegram.org/bottest-token/sendMessage",
        json={"ok": True, "result": {"message_id": 123}},
    )

    result = await send_deal_alert(
        bot_token="test-token",
        chat_id="12345",
        analysis=sample_analysis,
    )
    assert result is True
