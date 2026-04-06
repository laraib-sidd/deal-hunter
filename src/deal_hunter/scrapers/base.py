"""Base scraper interface."""

from __future__ import annotations

import abc
import logging

from deal_hunter.db.models import Listing

logger = logging.getLogger(__name__)


class BaseScraper(abc.ABC):
    """Abstract base class for all listing scrapers."""

    @property
    @abc.abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this source (e.g. 'techenclave', 'reddit')."""

    @abc.abstractmethod
    async def scrape(self, keywords: list[str] | None = None, max_pages: int = 3) -> list[Listing]:
        """Scrape listings and return normalized Listing objects.

        Args:
            keywords: Optional search terms to filter by.
            max_pages: Maximum pages/batches to fetch.

        Returns:
            List of Listing objects ready for DB insertion.
        """

    def _log_results(self, count: int) -> None:
        logger.info("[%s] Scraped %d listings", self.source_name, count)
