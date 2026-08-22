"""Scraper orchestrator — runs all scrapers concurrently.

build_scrapers is registry-driven (Open/Closed): adding a source = registering a factory in
SOURCES_, no `if` chain to modify.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from deal_hunter.config import AppConfig
from deal_hunter.db.models import Listing
from deal_hunter.scrapers.base import BaseScraper
from deal_hunter.scrapers.reddit import RedditScraper
from deal_hunter.scrapers.techenclave import TechEnclaveScraper

logger = logging.getLogger(__name__)


def _make_reddit(config: AppConfig) -> BaseScraper:
    return RedditScraper(
        client_id=config.reddit_client_id,
        client_secret=config.reddit_client_secret,
    )


# Registry: name -> factory(config). Add a source here; no `if` chain to touch.
SOURCES: dict[str, Callable[[AppConfig], BaseScraper]] = {
    "techenclave": lambda config: TechEnclaveScraper(),
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
) -> list[Listing]:
    """Run all scrapers concurrently, collecting results."""
    tasks = [s.scrape(keywords=keywords, max_pages=max_pages) for s in scrapers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_listings: list[Listing] = []
    healthy: list[str] = []
    failed: list[str] = []
    for scraper, result in zip(scrapers, results):
        if isinstance(result, Exception):
            logger.error("[%s] Scraper failed: %s", scraper.source_name, result)
            failed.append(scraper.source_name)
            continue
        all_listings.extend(result)
        healthy.append(scraper.source_name)
        logger.info("[%s] Returned %d listings", scraper.source_name, len(result))

    if failed:
        logger.warning("Sources failed this cycle: %s", ", ".join(failed))
    logger.info("Total listings scraped: %d", len(all_listings))
    return all_listings
