"""Tests for DB engine and upsert logic."""

from __future__ import annotations

from pathlib import Path

import pytest

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
