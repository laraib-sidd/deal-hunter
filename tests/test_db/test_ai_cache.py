"""Tests for AI budget + AI-result cache (M5)."""
from __future__ import annotations

from deal_hunter.db.ai_cache_repo import AiBudget, cache_get, cache_put
from deal_hunter.db.engine import get_engine


class TestAiBudget:
    def test_budget_allows_up_to_cap(self) -> None:
        b = AiBudget(max_calls=3)
        assert b.allow() is True
        assert b.allow() is True
        assert b.allow() is True
        assert b.allow() is False  # exhausted
        assert b.remaining == 0

    def test_default_cap(self) -> None:
        b = AiBudget()
        assert b.remaining == 500


class TestAiCache:
    def test_put_get_roundtrip(self, tmp_path) -> None:
        e = get_engine(tmp_path / "a.db")
        cache_put(e, "fp-1", '{"canonical_name":"x"}')
        assert cache_get(e, "fp-1") == '{"canonical_name":"x"}'
        assert cache_get(e, "fp-missing") is None

    def test_put_overwrites(self, tmp_path) -> None:
        e = get_engine(tmp_path / "a.db")
        cache_put(e, "fp", "v1")
        cache_put(e, "fp", "v2")
        assert cache_get(e, "fp") == "v2"
