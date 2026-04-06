"""Scraper orchestrator — runs all scrapers concurrently."""

from __future__ import annotations

import asyncio
import logging

from deal_hunter.config import AppConfig
from deal_hunter.db.models import Listing
from deal_hunter.scrapers.base import BaseScraper
from deal_hunter.scrapers.reddit import RedditScraper
from deal_hunter.scrapers.techenclave import TechEnclaveScraper

logger = logging.getLogger(__name__)


def build_scrapers(config: AppConfig) -> list[BaseScraper]:
    """Build scraper instances based on config."""
    scrapers: list[BaseScraper] = []

    if "techenclave" in config.sources:
        scrapers.append(TechEnclaveScraper())

    if "reddit" in config.sources:
        scrapers.append(RedditScraper(
            client_id=config.reddit_client_id,
            client_secret=config.reddit_client_secret,
        ))

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
    for scraper, result in zip(scrapers, results):
        if isinstance(result, Exception):
            logger.error("[%s] Scraper failed: %s", scraper.source_name, result)
            continue
        all_listings.extend(result)
        logger.info("[%s] Returned %d listings", scraper.source_name, len(result))

    logger.info("Total listings scraped: %d", len(all_listings))
    return all_listings
