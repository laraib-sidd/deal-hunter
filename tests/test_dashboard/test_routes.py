"""Tests for dashboard routes (FastAPI TestClient) + marketplace filters."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from deal_hunter.dashboard import app as app_module
from deal_hunter.dashboard.app import app
from deal_hunter.db.engine import get_engine
from deal_hunter.db.models import Listing, WatchHit, WatchRule
from deal_hunter.db.repo_meta import log_run


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    engine = get_engine(tmp_path / "dash.db")
    monkeypatch.setattr(app_module, "_engine", engine)
    return TestClient(app)


def _add_listing(engine, **kwargs) -> Listing:
    defaults = {
        "source": "reddit",
        "source_id": "x1",
        "fingerprint": "fp1",
        "url": "https://example.com/1",
        "title": "RTX 3060 for sale",
        "price": 15000.0,
        "status": "active",
        "scraped_at": datetime.now(UTC),
        "last_confirmed_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    row = Listing(**defaults)
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


class TestDashboardRoutes:
    def test_index_200(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert "Deal Hunter" in r.text

    def test_index_mutes_buy_signals_when_zero(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert "no buy signals yet" in r.text
        assert "▲ buy signals" not in r.text

    def test_marketplace_200(self, client: TestClient) -> None:
        r = client.get("/marketplace")
        assert r.status_code == 200
        assert "Listing" in r.text or "no listings" in r.text.lower()

    def test_marketplace_category_filter(self, client: TestClient) -> None:
        r = client.get("/marketplace?category=gpu")
        assert r.status_code == 200

    def test_marketplace_verdict_filter(self, client: TestClient, tmp_path) -> None:
        engine = get_engine(tmp_path / "dash.db")
        _add_listing(engine, source_id="a", deal_verdict="BUY", deal_score=8, canonical_name="RTX 3060")
        _add_listing(engine, source_id="b", deal_verdict="PASS", deal_score=3, canonical_name="RTX 3070")
        r = client.get("/marketplace?verdict=BUY")
        assert r.status_code == 200
        assert "RTX 3060" in r.text
        assert "RTX 3070" not in r.text

    def test_deals_200(self, client: TestClient) -> None:
        r = client.get("/deals")
        assert r.status_code == 200

    def test_deals_empty_no_priced(self, client: TestClient) -> None:
        r = client.get("/deals")
        assert r.status_code == 200
        assert "No priced listings yet" in r.text

    def test_deals_empty_no_scored(self, client: TestClient, tmp_path) -> None:
        engine = get_engine(tmp_path / "dash.db")
        _add_listing(engine, source_id="priced", price=12000.0, deal_score=None)
        r = client.get("/deals")
        assert r.status_code == 200
        assert "scoring has not been written onto these rows" in r.text

    def test_deals_filter_source(self, client: TestClient, tmp_path) -> None:
        engine = get_engine(tmp_path / "dash.db")
        _add_listing(
            engine,
            source_id="r1",
            source="reddit",
            deal_score=7,
            deal_verdict="BUY",
            canonical_name="RTX 3060",
        )
        _add_listing(
            engine,
            source_id="t1",
            source="techenclave",
            deal_score=8,
            deal_verdict="BUY",
            canonical_name="RTX 3070",
        )
        r = client.get("/deals?source=reddit")
        assert r.status_code == 200
        assert "RTX 3060" in r.text
        assert "RTX 3070" not in r.text

    def test_deals_filter_verdict(self, client: TestClient, tmp_path) -> None:
        engine = get_engine(tmp_path / "dash.db")
        _add_listing(engine, source_id="b1", deal_score=8, deal_verdict="BUY", canonical_name="RTX 3060")
        _add_listing(engine, source_id="n1", deal_score=7, deal_verdict="NEGOTIATE", canonical_name="RTX 3070")
        r = client.get("/deals?verdict=BUY")
        assert r.status_code == 200
        assert "RTX 3060" in r.text
        assert "RTX 3070" not in r.text

    def test_deals_filter_search(self, client: TestClient, tmp_path) -> None:
        engine = get_engine(tmp_path / "dash.db")
        _add_listing(engine, source_id="s1", deal_score=8, deal_verdict="BUY", canonical_name="RTX 3060")
        _add_listing(engine, source_id="s2", deal_score=8, deal_verdict="BUY", canonical_name="Ryzen 5600")
        r = client.get("/deals?q=ryzen")
        assert r.status_code == 200
        assert "Ryzen 5600" in r.text
        assert "RTX 3060" not in r.text

    def test_live_pill_off_without_run(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert "live-off" in r.text
        assert "> OFF<" in r.text or " OFF<" in r.text

    def test_live_pill_live_recent_run(self, client: TestClient, tmp_path) -> None:
        engine = get_engine(tmp_path / "dash.db")
        log_run(
            engine,
            {
                "run_id": "abc123",
                "source": "all",
                "scraped": 1,
                "new": 1,
                "scored": 1,
                "failed": False,
                "duration_ms": 100,
                "circuit_state": "closed",
                "started_at": datetime.now(UTC),
            },
        )
        r = client.get("/")
        assert r.status_code == 200
        assert "live-ok" in r.text
        assert "LIVE" in r.text

    def test_watch_200(self, client: TestClient) -> None:
        r = client.get("/watch")
        assert r.status_code == 200

    def test_watch_hit_shows_listing_title(self, client: TestClient, tmp_path) -> None:
        engine = get_engine(tmp_path / "dash.db")
        listing = _add_listing(engine, source_id="wh1", title="Used RTX 3080 bargain", canonical_name="RTX 3080")
        with Session(engine) as session:
            rule = WatchRule(query="rtx 3080", label="3080 watch")
            session.add(rule)
            session.commit()
            session.refresh(rule)
            session.add(WatchHit(rule_id=rule.id, listing_id=listing.id))
            session.commit()
        r = client.get("/watch")
        assert r.status_code == 200
        assert "RTX 3080" in r.text

    def test_health_503_without_run(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 503
        assert "last_run: none yet" in r.text

    def test_health_503_stale_run(self, client: TestClient, tmp_path) -> None:
        engine = get_engine(tmp_path / "dash.db")
        log_run(
            engine,
            {
                "run_id": "stale1",
                "source": "all",
                "scraped": 1,
                "new": 0,
                "scored": 1,
                "failed": False,
                "duration_ms": 100,
                "circuit_state": "closed",
                "started_at": datetime.now(UTC) - timedelta(hours=4),
            },
        )
        r = client.get("/health")
        assert r.status_code == 503
        assert "last_run: all" in r.text

    def test_health_200_recent_run(self, client: TestClient, tmp_path) -> None:
        engine = get_engine(tmp_path / "dash.db")
        log_run(
            engine,
            {
                "run_id": "fresh1",
                "source": "all",
                "scraped": 2,
                "new": 1,
                "scored": 1,
                "failed": False,
                "duration_ms": 200,
                "circuit_state": "closed",
                "started_at": datetime.now(UTC),
            },
        )
        r = client.get("/health")
        assert r.status_code == 200
        assert "last_run: all" in r.text

    def test_unknown_product_404(self, client: TestClient) -> None:
        r = client.get("/product/definitely-not-a-real-product-xyz")
        assert r.status_code == 404
