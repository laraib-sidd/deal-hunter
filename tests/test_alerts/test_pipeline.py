"""Tests for score_delta, decide_alerts, and dispatch."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlmodel import Session, select

from deal_hunter.alerts.pipeline import decide_alerts, dispatch, score_delta
from deal_hunter.analysis.schemas import DealAnalysis
from deal_hunter.bot import search_listings
from deal_hunter.config import AppConfig, TelegramConfig
from deal_hunter.db.engine import get_engine
from deal_hunter.db.ingest import IngestionService
from deal_hunter.db.models import Listing


def _engine(tmp_path):
    return get_engine(tmp_path / "alerts.db")


def _listing(
    source_id: str,
    title: str = "RTX 3060 12GB",
    price: float = 5000.0,
    category: str = "gpu",
    location: str | None = None,
    **kwargs,
) -> Listing:
    return Listing(
        source="reddit",
        source_id=source_id,
        fingerprint=Listing.compute_fingerprint(title, price, location),
        url=f"https://reddit.com/{source_id}",
        title=title,
        price=price,
        category=category,
        location=location,
        **kwargs,
    )


def _analysis(score: int = 8, verdict: str = "BUY") -> DealAnalysis:
    return DealAnalysis(
        canonical_name="NVIDIA GeForce RTX 3060",
        category="gpu",
        brand="NVIDIA",
        asking_price=5000,
        fair_market_low=10000,
        fair_market_high=15000,
        fair_market_mid=12500,
        msrp=29500,
        price_vs_fair_pct=-60.0,
        deal_score=score,
        verdict=verdict,
        reasoning="Test deal",
        red_flags=[],
        confidence=0.9,
    )


class TestScoreDelta:
    @pytest.mark.asyncio
    async def test_persists_scores_for_priced_hardware(self, tmp_path) -> None:
        engine = _engine(tmp_path)
        svc = IngestionService(engine)
        svc.ingest_batch([_listing("a")])
        with Session(engine) as session:
            listing = session.exec(select(Listing).where(Listing.source_id == "a")).first()

        analyses = await score_delta(engine, [listing], ai_api_key="")
        assert listing.id in analyses
        assert analyses[listing.id].deal_score >= 1

        with Session(engine) as session:
            row = session.get(Listing, listing.id)
            assert row.deal_score is not None
            assert row.deal_verdict is not None

    @pytest.mark.asyncio
    async def test_skips_no_price(self, tmp_path) -> None:
        engine = _engine(tmp_path)
        listing = _listing("b", price=None)
        analyses = await score_delta(engine, [listing], ai_api_key="")
        assert analyses == {}

    @pytest.mark.asyncio
    async def test_skips_wtb_and_other(self, tmp_path) -> None:
        engine = _engine(tmp_path)
        svc = IngestionService(engine)
        svc.ingest_batch([
            _listing("wtb", category="wtb"),
            _listing("other", category="other"),
        ])
        with Session(engine) as session:
            rows = list(session.exec(select(Listing)).all())

        analyses = await score_delta(engine, rows, ai_api_key="")
        assert analyses == {}


class TestDecideAlerts:
    def test_keeps_buy_and_negotiate_above_threshold(self) -> None:
        listings = [_listing("a"), _listing("b"), _listing("c")]
        listings[0].id = 1
        listings[1].id = 2
        listings[2].id = 3
        analyses = {
            1: _analysis(8, "BUY"),
            2: _analysis(7, "NEGOTIATE"),
            3: _analysis(9, "PASS"),
        }
        alerts = decide_alerts(listings, analyses, min_score=6)
        assert len(alerts) == 2
        assert {pair[0].id for pair in alerts} == {1, 2}

    def test_skips_already_alerted(self) -> None:
        listing = _listing("a")
        listing.id = 1
        listing.alerted_at = datetime.now(UTC)
        analyses = {1: _analysis(8, "BUY")}
        assert decide_alerts([listing], analyses, min_score=6) == []

    def test_re_alerts_on_eight_percent_drop(self) -> None:
        listing = _listing("a", price=9000.0)
        listing.id = 1
        listing.alerted_at = datetime.now(UTC)
        analyses = {1: _analysis(8, "BUY")}
        drops = [(listing, 10000.0, 9000.0)]
        alerts = decide_alerts([listing], analyses, min_score=6, price_drops=drops)
        assert len(alerts) == 1

    def test_ignores_small_price_drop(self) -> None:
        listing = _listing("a", price=9500.0)
        listing.id = 1
        listing.alerted_at = datetime.now(UTC)
        analyses = {1: _analysis(8, "BUY")}
        drops = [(listing, 10000.0, 9500.0)]
        assert decide_alerts([listing], analyses, min_score=6, price_drops=drops) == []

    def test_caps_at_five(self) -> None:
        listings = []
        analyses = {}
        for i in range(8):
            listing = _listing(str(i))
            listing.id = i + 1
            listings.append(listing)
            analyses[i + 1] = _analysis(10 - i, "BUY")
        alerts = decide_alerts(listings, analyses, min_score=6)
        assert len(alerts) == 5
        assert alerts[0][1].deal_score >= alerts[-1][1].deal_score


class TestDispatch:
    @pytest.mark.asyncio
    async def test_sends_listings_then_summary_and_marks_alerted(
        self, tmp_path, httpx_mock
    ) -> None:
        engine = _engine(tmp_path)
        svc = IngestionService(engine)
        svc.ingest_batch([_listing("a")])
        with Session(engine) as session:
            listing = session.exec(select(Listing).where(Listing.source_id == "a")).first()

        config = AppConfig(telegram=TelegramConfig(enabled=True, bot_token="tok", chat_id="1"))
        analysis = _analysis()

        for _ in range(2):
            httpx_mock.add_response(
                url="https://api.telegram.org/bottok/sendMessage",
                json={"ok": True, "result": {"message_id": 1}},
            )

        await dispatch(engine, config, [(listing, analysis)])

        requests = httpx_mock.get_requests()
        assert len(requests) == 2
        assert "RTX 3060" in requests[0].content.decode()
        assert "Deal Hunter" in requests[1].content.decode()

        with Session(engine) as session:
            row = session.get(Listing, listing.id)
            assert row.alerted_at is not None

    @pytest.mark.asyncio
    async def test_empty_alerts_send_nothing(self, tmp_path, httpx_mock) -> None:
        engine = _engine(tmp_path)
        config = AppConfig(telegram=TelegramConfig(enabled=True, bot_token="tok", chat_id="1"))
        await dispatch(engine, config, [])
        assert httpx_mock.get_requests() == []


class TestBotLocationFilter:
    def test_search_listings_filters_by_location(self, tmp_path) -> None:
        engine = _engine(tmp_path)
        svc = IngestionService(engine)
        svc.ingest_batch([
            _listing("delhi", location="Delhi NCR"),
            _listing("mumbai", location="Mumbai"),
        ])
        results = search_listings(engine, "rtx 3060", None, locations=["delhi"])
        assert len(results) == 1
        assert results[0].source_id == "delhi"
