"""TechEnclave scraper — uses Discourse JSON API (no auth needed)."""

from __future__ import annotations

import logging
import time
from datetime import datetime

from deal_hunter.config import AppConfig
from deal_hunter.db.models import Listing
from deal_hunter.scrapers.base import BaseScraper
from deal_hunter.scrapers.http import HttpFetcher
from deal_hunter.scrapers.parsing import classify_intent, extract_location, extract_price, strip_html

logger = logging.getLogger(__name__)

BASE_URL = "https://techenclave.com"
# Trading Post subcategories (discovered via /categories.json)
MARKETPLACE_CATEGORIES = {
    64: "classifieds",      # User-to-user listings
    61: "flash-deals",      # Quick sale items
    19: "garage-sale",      # Bulk/clearance sales
    18: "looking-to-buy",   # WTB posts
}
DEFAULT_CATEGORY_ID = 64  # Classifieds
MAX_DETAIL_FETCHES = 40


def _watermark_max(known_ids: set[str]) -> int | None:
    if not known_ids:
        return None
    return max(int(topic_id) for topic_id in known_ids)


def _topic_was_bumped(topic: dict) -> bool:
    created_at = topic.get("created_at")
    if not created_at:
        return False
    for field in ("bumped_at", "last_posted_at"):
        bumped_at = topic.get(field)
        if bumped_at and bumped_at > created_at:
            return True
    return False


def _past_watermark(topic_id: int, known_ids: set[str]) -> bool:
    watermark = _watermark_max(known_ids)
    return watermark is not None and topic_id <= watermark


class TechEnclaveScraper(BaseScraper):
    """Scrapes TechEnclave Trading Post > Classifieds via Discourse JSON API."""

    list_fetch_exhausted: bool = False

    def __init__(self, config: AppConfig | None = None) -> None:
        cfg = config or AppConfig()
        self._request_delay = cfg.techenclave_request_delay
        self._timeout = cfg.techenclave_timeout
        self._deadline_seconds = cfg.techenclave_deadline_seconds
        self._netskope_ca = cfg.netskope_ca_path

    @property
    def source_name(self) -> str:
        return "techenclave"

    async def scrape(
        self,
        keywords: list[str] | None = None,
        max_pages: int = 3,
        known_ids: set[str] | None = None,
    ) -> list[Listing]:
        """Fetch listings from TechEnclave classifieds.

        Uses the shared HttpFetcher (timeout + retry/backoff + global deadline) so a slow
        or hanging page cannot block the whole run indefinitely.
        """
        self.list_fetch_exhausted = False
        deadline = time.monotonic() + self._deadline_seconds
        known = known_ids or set()

        async with HttpFetcher(timeout=self._timeout, netskope_ca=self._netskope_ca) as client:
            if keywords:
                topic_refs = await self._search_topics(client, keywords, max_pages, known)
            else:
                topic_refs = await self._fetch_category_topics(client, max_pages, known)

            listings: list[Listing] = []
            detail_fetches = 0
            for cat_id, cat_slug, topic in topic_refs:
                if time.monotonic() > deadline:
                    logger.warning("TE scrape hit global deadline — stopping early")
                    break
                if detail_fetches >= MAX_DETAIL_FETCHES:
                    logger.info("TE detail-fetch cap (%d) reached — stopping early", MAX_DETAIL_FETCHES)
                    break

                topic_id = str(topic["id"])
                if topic_id in known and not _topic_was_bumped(topic):
                    continue

                listing = await self._fetch_topic_detail(client, topic, cat_id, cat_slug)
                detail_fetches += 1
                if listing:
                    listings.append(listing)

            self._log_results(len(listings))
            return listings

    async def _fetch_category_topics(
        self,
        client: HttpFetcher,
        max_pages: int,
        known_ids: set[str],
    ) -> list[tuple[int, str, dict]]:
        """Paginate marketplace categories; stop paging when a known topic id appears."""
        topic_refs: list[tuple[int, str, dict]] = []
        seen_ids: set[int] = set()

        for cat_id, cat_slug in MARKETPLACE_CATEGORIES.items():
            for page in range(max_pages):
                url = f"{BASE_URL}/c/trading-post/{cat_slug}/{cat_id}.json"
                resp = await client.get(url, params={"page": page}, host_min_interval=self._request_delay)
                if resp.status == "exhausted":
                    self.list_fetch_exhausted = True
                    logger.warning("TE %s page %d exhausted retries", cat_slug, page)
                    break
                if resp.status != "success":
                    logger.warning("TE %s page %d returned %d", cat_slug, page, resp.status_code)
                    break

                data = resp.json()
                page_topics = data.get("topic_list", {}).get("topics", [])
                if not page_topics:
                    break

                stop_paging = False
                for topic in page_topics:
                    topic_id = topic["id"]
                    if _past_watermark(topic_id, known_ids):
                        if str(topic_id) in known_ids and _topic_was_bumped(topic):
                            if topic_id not in seen_ids:
                                seen_ids.add(topic_id)
                                topic_refs.append((cat_id, cat_slug, topic))
                        stop_paging = True
                        break
                    if topic_id in seen_ids:
                        continue
                    seen_ids.add(topic_id)
                    topic_refs.append((cat_id, cat_slug, topic))

                logger.debug("TE %s page %d: %d topics", cat_slug, page, len(page_topics))
                if stop_paging:
                    break

        return topic_refs

    async def _search_topics(
        self,
        client: HttpFetcher,
        keywords: list[str],
        max_pages: int,
        known_ids: set[str],
    ) -> list[tuple[int, str, dict]]:
        """Search classifieds using Discourse search API with paging."""
        topic_refs: list[tuple[int, str, dict]] = []
        seen_ids: set[int] = set()

        for keyword in keywords[:5]:
            query = f"{keyword} category:{DEFAULT_CATEGORY_ID}"
            for page in range(max_pages):
                resp = await client.get(
                    f"{BASE_URL}/search.json",
                    params={"q": query, "page": page},
                    host_min_interval=self._request_delay,
                )
                if resp.status == "exhausted":
                    self.list_fetch_exhausted = True
                    logger.warning("TE search for '%s' page %d exhausted retries", keyword, page)
                    break
                if resp.status != "success":
                    logger.warning("TE search for '%s' page %d failed", keyword, page)
                    break

                data = resp.json()
                page_topics = data.get("topics", [])
                if not page_topics:
                    break

                stop_paging = False
                for topic in page_topics:
                    topic_id = topic["id"]
                    if _past_watermark(topic_id, known_ids):
                        if str(topic_id) in known_ids and _topic_was_bumped(topic):
                            if topic_id not in seen_ids:
                                seen_ids.add(topic_id)
                                topic_refs.append((DEFAULT_CATEGORY_ID, "classifieds", topic))
                        stop_paging = True
                        break
                    if topic_id in seen_ids:
                        continue
                    seen_ids.add(topic_id)
                    topic_refs.append((DEFAULT_CATEGORY_ID, "classifieds", topic))

                if stop_paging:
                    break

        return topic_refs

    async def _fetch_topic_detail(
        self,
        client: HttpFetcher,
        topic_summary: dict,
        cat_id: int,
        cat_slug: str,
    ) -> Listing | None:
        """Fetch full topic and build a Listing."""
        topic_id = topic_summary["id"]
        resp = await client.get(
            f"{BASE_URL}/t/{topic_id}.json",
            host_min_interval=self._request_delay,
        )
        if resp.status != "success":
            logger.debug("TE topic %d fetch failed (%s)", topic_id, resp.status)
            return None

        data = resp.json()
        posts = data.get("post_stream", {}).get("posts", [])
        if not posts:
            return None

        first_post = posts[0]
        body_html = first_post.get("cooked", "")
        body_text = strip_html(body_html)
        title = data.get("title", topic_summary.get("title", ""))

        price = extract_price(body_html)
        location = extract_location(body_html)

        posted_at = None
        created_str = data.get("created_at", "")
        if created_str:
            try:
                posted_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        slug = data.get("slug", "")
        url = f"{BASE_URL}/t/{slug}/{topic_id}"

        intent = classify_intent(title, body_text, category_hint=cat_slug)

        return Listing(
            source="techenclave",
            source_id=str(topic_id),
            fingerprint=Listing.compute_fingerprint(title, price, location),
            url=url,
            title=title,
            description=body_text,
            price=price,
            location=location,
            seller_name=first_post.get("username", ""),
            posted_at=posted_at,
            category=intent,
        )
