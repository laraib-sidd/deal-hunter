"""Scraper orchestrator — runs all scrapers concurrently.

build_scrapers is registry-driven (Open/Closed): adding a source = registering a factory in
SOURCES_, no `if` chain to modify.

Also contains a per-source circuit breaker so a source that keeps failing is opened
(fail-fast, skipped) for a cooldown window instead of blocking/hammering every cycle.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from deal_hunter.config import AppConfig
from deal_hunter.db.models import Listing
from deal_hunter.scrapers.base import BaseScraper
from deal_hunter.scrapers.reddit import RedditScraper
from deal_hunter.scrapers.techenclave import TechEnclaveScraper

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 3  # consecutive failures before opening the circuit
COOLDOWN_SECONDS = 300.0  # how long an open circuit stays open before retrying


class CircuitBreaker:
    """Per-source failure tracking: after N failures, open (skip) for a cooldown."""

    def __init__(
        self,
        threshold: int = FAILURE_THRESHOLD,
        cooldown: float = COOLDOWN_SECONDS,
    ) -> None:
        self._threshold = threshold
        self._cooldown = cooldown
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def is_open(self, source: str) -> bool:
        """Whether a source is currently tripped and skipping work."""
        until = self._open_until.get(source, 0.0)
        if time.monotonic() < until:
            return True
        if until:  # cooldown elapsed — reset failures, allow one probe
            self._failures.pop(source, None)
            self._open_until.pop(source, None)
        return False

    def record_failure(self, source: str) -> str:
        """Record a failure; open the circuit if threshold reached. Returns state."""
        self._failures[source] = self._failures.get(source, 0) + 1
        n = self._failures[source]
        if n >= self._threshold:
            self._open_until[source] = time.monotonic() + self._cooldown
            self._failures.pop(source, None)
            logger.warning("[%s] circuit OPEN after %d failures", source, n)
            return "open"
        return "tripped"

    def record_success(self, source: str) -> None:
        self._failures.pop(source, None)
        if source in self._open_until:
            self._open_until.pop(source, None)


def _make_reddit(config: AppConfig) -> BaseScraper:
    return RedditScraper(config=config)


# Registry: name -> factory(config). Add a source here; no `if` chain to touch.
SOURCES: dict[str, Callable[[AppConfig], BaseScraper]] = {
    "techenclave": lambda config: TechEnclaveScraper(config=config),
    "reddit": _make_reddit,
}


def build_scrapers(config: AppConfig) -> list[BaseScraper]:
    """Build scraper instances based on config.sources, via the SOURCES registry."""
    scrapers: list[BaseScraper] = []
    for name in config.sources:
        factory = SOURCES.get(name)
        if factory is None:
            logger.warning("Unknown source '%s' — ignoring", name)
            continue
        scrapers.append(factory(config))
    return scrapers


async def run_scrapers(
    scrapers: list[BaseScraper],
    keywords: list[str] | None = None,
    max_pages: int = 3,
    circuit: CircuitBreaker | None = None,
    max_concurrent: int = 5,
) -> list[Listing]:
    """Run all scrapers (that aren't circuit-open) concurrently, collecting results."""
    breaker = circuit or CircuitBreaker()
    sem = asyncio.Semaphore(max_concurrent)

    async def _run(scraper: BaseScraper) -> list[Listing]:
        source = scraper.source_name
        if breaker.is_open(source):
            logger.warning("[%s] circuit open — skipping this cycle", source)
            return []
        async with sem:
            try:
                result = await scraper.scrape(keywords=keywords, max_pages=max_pages)
            except Exception as exc:  # noqa: BLE001 - fail fast, never crash the run
                breaker.record_failure(source)
                logger.error("[%s] Scraper failed: %s", source, exc)
                return []
        breaker.record_success(source)
        logger.info("[%s] Returned %d listings", source, len(result))
        return result

    tasks = [_run(s) for s in scrapers]
    batch = await asyncio.gather(*tasks, return_exceptions=True)
    all_listings: list[Listing] = []
    for result in batch:
        if isinstance(result, list):
            all_listings.extend(result)

    logger.info("Total listings scraped: %d", len(all_listings))
    return all_listings
