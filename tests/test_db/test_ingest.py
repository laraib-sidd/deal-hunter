"""Tests for IngestionService (new/seen/reactivated/dedup/price drops)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from deal_hunter.analysis.schemas import DealAnalysis, RedFlag
from deal_hunter.db.engine import get_engine
from deal_hunter.db.ingest import IngestionService, mark_alerted, mark_stale, persist_scores
from deal_hunter.db.models import Listing, PriceSnapshot, Seller


def _listing(
    source_id: str,
    title: str = "RTX 3060",
    price: float = 15000.0,
    seller_name: str | None = "seller_a",
    **kwargs,
) -> Listing:
    return Listing(
        source="reddit",
        source_id=source_id,
        fingerprint=Listing.compute_fingerprint(title, price, None),
        url=f"https://reddit.com/{source_id}",
        title=title,
        price=price,
        seller_name=seller_name,
        **kwargs,
    )


def _engine(tmp_path):
    return get_engine(tmp_path / "t.db")


class TestIngestion:
    def test_new_listings_added(self, tmp_path) -> None:
        svc = IngestionService(_engine(tmp_path))
        res = svc.ingest_batch([_listing("a"), _listing("b")])
        assert len(res.new) == 2
        assert res.duplicate_exact == 0

    def test_duplicate_source_id_skipped(self, tmp_path) -> None:
        svc = IngestionService(_engine(tmp_path))
        svc.ingest_batch([_listing("a")])
        res = svc.ingest_batch([_listing("a")])
        assert res.new == []
        assert res.seen  # existing active listing marked seen

    def test_reactivates_dead(self, tmp_path) -> None:
        e = _engine(tmp_path)
        svc = IngestionService(e)
        svc.ingest_batch([_listing("a")])
        with Session(e) as s:
            lst = s.exec(select(Listing).where(Listing.source_id == "a")).first()
            lst.status = "dead"
            s.commit()
        res = svc.ingest_batch([_listing("a")])
        assert res.reactivated

    def test_seller_created(self, tmp_path) -> None:
        e = _engine(tmp_path)
        svc = IngestionService(e)
        svc.ingest_batch([_listing("a", seller_name="seller_z")])
        with Session(e) as s:
            sellers = s.exec(select(Seller)).all()
            assert len(sellers) == 1
            assert sellers[0].source_key == "seller_z"

    def test_price_drop_recorded(self, tmp_path) -> None:
        e = _engine(tmp_path)
        svc = IngestionService(e)
        svc.ingest_batch([_listing("a", price=20000.0)])
        res = svc.ingest_batch([_listing("a", price=15000.0)])
        assert len(res.price_drops) == 1
        listing, old_price, new_price = res.price_drops[0]
        assert old_price == 20000.0
        assert new_price == 15000.0
        with Session(e) as s:
            snaps = s.exec(select(PriceSnapshot)).all()
            assert len(snaps) == 1
            assert snaps[0].price == 15000.0

    def test_unchanged_price_no_snapshot(self, tmp_path) -> None:
        e = _engine(tmp_path)
        svc = IngestionService(e)
        svc.ingest_batch([_listing("a", price=15000.0)])
        svc.ingest_batch([_listing("a", price=15000.0)])
        with Session(e) as s:
            snaps = s.exec(select(PriceSnapshot)).all()
            assert snaps == []

    def test_price_increase_no_price_drop(self, tmp_path) -> None:
        e = _engine(tmp_path)
        svc = IngestionService(e)
        svc.ingest_batch([_listing("a", price=15000.0)])
        res = svc.ingest_batch([_listing("a", price=18000.0)])
        assert res.price_drops == []
        with Session(e) as s:
            snaps = s.exec(select(PriceSnapshot)).all()
            assert len(snaps) == 1


class TestPersistScores:
    def test_writes_analysis_fields(self, tmp_path) -> None:
        e = _engine(tmp_path)
        svc = IngestionService(e)
        svc.ingest_batch([_listing("a")])
        with Session(e) as s:
            lst = s.exec(select(Listing).where(Listing.source_id == "a")).first()
            listing_id = lst.id
        analysis = DealAnalysis(
            canonical_name="NVIDIA GeForce RTX 3060",
            category="gpu",
            brand="NVIDIA",
            asking_price=15000,
            fair_market_low=18000,
            fair_market_high=22000,
            fair_market_mid=20000,
            msrp=29990,
            price_vs_fair_pct=-25.0,
            deal_score=8,
            verdict="BUY",
            reasoning="Well below fair market",
            red_flags=[RedFlag(flag_type="mining_risk", severity="low", detail="used")],
            confidence=0.9,
        )
        persist_scores(e, [(listing_id, analysis)])
        with Session(e) as s:
            lst = s.get(Listing, listing_id)
            assert lst.deal_score == 8.0
            assert lst.deal_verdict == "BUY"
            assert lst.deal_reason == "Well below fair market"
            assert lst.canonical_name == "NVIDIA GeForce RTX 3060"
            assert "mining_risk" in (lst.red_flags_json or "")


class TestMarkAlerted:
    def test_sets_alerted_at(self, tmp_path) -> None:
        e = _engine(tmp_path)
        svc = IngestionService(e)
        svc.ingest_batch([_listing("a")])
        with Session(e) as s:
            lst = s.exec(select(Listing).where(Listing.source_id == "a")).first()
            assert lst.alerted_at is None
            listing_id = lst.id
        mark_alerted(e, [listing_id])
        with Session(e) as s:
            lst = s.get(Listing, listing_id)
            assert lst.alerted_at is not None


class TestMarkStale:
    def test_marks_old_active_listings(self, tmp_path) -> None:
        e = _engine(tmp_path)
        svc = IngestionService(e)
        old = datetime.now(UTC) - timedelta(days=22)
        svc.ingest_batch([_listing("a", posted_at=old)])
        count = mark_stale(e, datetime.now(UTC))
        assert count == 1
        with Session(e) as s:
            lst = s.exec(select(Listing).where(Listing.source_id == "a")).first()
            assert lst.status == "stale"

    def test_skips_recent_listings(self, tmp_path) -> None:
        e = _engine(tmp_path)
        svc = IngestionService(e)
        recent = datetime.now(UTC) - timedelta(days=5)
        svc.ingest_batch([_listing("a", posted_at=recent)])
        count = mark_stale(e, datetime.now(UTC))
        assert count == 0
