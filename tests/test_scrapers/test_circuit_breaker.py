"""Tests for the per-source CircuitBreaker."""
from __future__ import annotations


import pytest
import pytest_httpx

from deal_hunter.db.models import Listing
from deal_hunter.scrapers.base import BaseScraper
from deal_hunter.scrapers.http import HttpFetcher
from deal_hunter.scrapers.runner import CircuitBreaker, run_scrapers




class TestCircuitBreaker:
    def test_success_clears_failures(self) -> None:
        cb = CircuitBreaker(threshold=3)
        cb.record_failure("reddit")
        cb.record_success("reddit")
        assert cb.is_open("reddit") is False

    def test_failures_trip_but_not_open_below_threshold(self) -> None:
        cb = CircuitBreaker(threshold=3)
        assert cb.record_failure("src") == "tripped"
        assert cb.record_failure("src") == "tripped"
        assert cb.is_open("src") is False

    def test_threshold_opens_circuit(self) -> None:
        cb = CircuitBreaker(threshold=3)
        assert cb.record_failure("src") == "tripped"
        assert cb.record_failure("src") == "tripped"
        assert cb.record_failure("src") == "open"
        assert cb.is_open("src") is True  # within cooldown

    def test_cooldown_expiry_resets(self) -> None:
        cb = CircuitBreaker(threshold=3, cooldown=0.001)
        cb.record_failure("src")
        cb.record_failure("src")
        cb.record_failure("src")
        assert cb.is_open("src") is True
        # after the tiny cooldown elapses, next check should reset and allow
        import time

        time.sleep(0.01)
        assert cb.is_open("src") is False

class _ExhaustingListScraper(BaseScraper):
    """Simulates a scraper whose list fetch exhausts HttpFetcher retries."""

    @property
    def source_name(self) -> str:
        return "testsrc"

    async def scrape(self, **kwargs) -> list[Listing]:
        async with HttpFetcher(max_retries=0, base_backoff=0.01) as client:
            await client.get("https://example.test/list")
        return []


@pytest.mark.anyio
async def test_exhausted_list_fetch_trips_circuit_and_skips_cursor_advance(
    httpx_mock: pytest_httpx.HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    httpx_mock.add_response(url="https://example.test/list", status_code=503)

    advanced: list[tuple[str, list]] = []

    def _fake_advance(engine, source: str, listings: list) -> None:
        advanced.append((source, listings))

    monkeypatch.setattr("deal_hunter.scrapers.runner.advance_cursors", _fake_advance)
    monkeypatch.setattr("deal_hunter.scrapers.runner.load_known_ids", lambda engine, source: set())

    cb = CircuitBreaker(threshold=1)
    listings = await run_scrapers(
        [_ExhaustingListScraper()],
        engine=object(),
        circuit=cb,
    )

    assert listings == []
    assert advanced == []
    assert cb.is_open("testsrc") is True

