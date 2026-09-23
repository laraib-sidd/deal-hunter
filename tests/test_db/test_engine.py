"""Tests for DB engine and upsert logic."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlmodel import Session

from deal_hunter.db.engine import get_engine, get_recent_listings, search_listings, upsert_listings
from deal_hunter.db.models import Listing


@pytest.fixture
def tmp_engine(tmp_path: Path):
    return get_engine(tmp_path / "test.db")


def _make_listing(**kwargs) -> Listing:
    defaults = {
        "source": "test",
        "source_id": "t1",
        "fingerprint": "abc123",
        "url": "https://example.com/1",
        "title": "RTX 3060 for sale",
    }
    defaults.update(kwargs)
    return Listing(**defaults)


class TestUpsert:
    def test_insert_new(self, tmp_engine) -> None:
        listings = [_make_listing()]
        inserted, skipped = upsert_listings(tmp_engine, listings)
        assert inserted == 1
        assert skipped == 0

    def test_skip_duplicate(self, tmp_engine) -> None:
        upsert_listings(tmp_engine, [_make_listing()])
        # Second call with same source+source_id should skip
        inserted, skipped = upsert_listings(tmp_engine, [_make_listing()])
        assert inserted == 0
        assert skipped == 1

    def test_different_source_id_inserts(self, tmp_engine) -> None:
        upsert_listings(tmp_engine, [_make_listing(source_id="t1")])
        inserted, _ = upsert_listings(tmp_engine, [_make_listing(source_id="t2")])
        assert inserted == 1


class TestSearch:
    def test_search_by_title(self, tmp_engine) -> None:
        upsert_listings(tmp_engine, [
            _make_listing(source_id="a", title="RTX 3060 sale"),
            _make_listing(source_id="b", title="Ryzen 5600X sale"),
        ])
        results = search_listings(tmp_engine, "RTX")
        assert len(results) == 1
        assert "RTX" in results[0].title

    def test_recent_listings(self, tmp_engine) -> None:
        upsert_listings(tmp_engine, [
            _make_listing(source_id="a"),
            _make_listing(source_id="b"),
        ])
        results = get_recent_listings(tmp_engine, limit=10)
        assert len(results) == 2


class TestFingerprint:
    def test_ignores_price(self) -> None:
        fp1 = Listing.compute_fingerprint("RTX 3060", 15000.0, "Mumbai")
        fp2 = Listing.compute_fingerprint("RTX 3060", 12000.0, "Mumbai")
        assert fp1 == fp2

    def test_differs_by_location(self) -> None:
        fp1 = Listing.compute_fingerprint("RTX 3060", 15000.0, "Mumbai")
        fp2 = Listing.compute_fingerprint("RTX 3060", 15000.0, "Delhi")
        assert fp1 != fp2


class TestMigration:
    def test_unique_index_on_source_pair(self, tmp_engine) -> None:
        insp = sa_inspect(tmp_engine)
        index_names = {ix["name"] for ix in insp.get_indexes("listings")}
        assert "uq_listing_source_item" in index_names

    def test_dedupes_before_unique_index(self, tmp_engine) -> None:
        from sqlalchemy import text
        from sqlmodel import select

        from deal_hunter.db.migrate import migrate

        with tmp_engine.begin() as conn:
            conn.execute(text("DROP INDEX IF EXISTS uq_listing_source_item"))
            conn.execute(text(
                "INSERT INTO listings (source, source_id, fingerprint, url, title, "
                "currency, category, status, times_seen, seen, scraped_at) "
                "VALUES ('test', 'dup', 'fp1', 'https://example.com/1', 'A', "
                "'INR', 'other', 'active', 1, 0, datetime('now'))"
            ))
            conn.execute(text(
                "INSERT INTO listings (source, source_id, fingerprint, url, title, "
                "currency, category, status, times_seen, seen, scraped_at) "
                "VALUES ('test', 'dup', 'fp2', 'https://example.com/2', 'B', "
                "'INR', 'other', 'active', 1, 0, datetime('now'))"
            ))
        migrate(tmp_engine)
        with Session(tmp_engine) as s:
            rows = s.exec(select(Listing).where(Listing.source_id == "dup")).all()
            assert len(rows) == 1
            assert rows[0].fingerprint == "fp1"
