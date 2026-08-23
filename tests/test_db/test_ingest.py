"""Tests for IngestionService (new/seen/reactivated/dedup)."""
from __future__ import annotations

from deal_hunter.db.engine import get_engine
from deal_hunter.db.ingest import IngestionService
from deal_hunter.db.models import Listing, Seller


def _listing(
    source_id: str,
    title: str = "RTX 3060",
    price: float = 15000.0,
    seller_name: str | None = "seller_a",
) -> Listing:
    return Listing(
        source="reddit",
        source_id=source_id,
        fingerprint=Listing.compute_fingerprint(title, price, None),
        url=f"https://reddit.com/{source_id}",
        title=title,
        price=price,
        seller_name=seller_name,
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
        # mark it dead
        from sqlmodel import Session, select

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
        from sqlmodel import Session, select

        with Session(e) as s:
            sellers = s.exec(select(Seller)).all()
            assert len(sellers) == 1
            assert sellers[0].source_key == "seller_z"
