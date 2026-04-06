"""TechEnclave scraper — uses Discourse JSON API (no auth needed)."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

import httpx

from deal_hunter.db.models import Listing
from deal_hunter.scrapers.base import BaseScraper

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
REQUEST_DELAY = 1.5  # seconds between requests (respect rate limits)

# Price extraction from Discourse post HTML
_PRICE_PATTERNS = [
    re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+)", re.IGNORECASE),
    re.compile(r"([\d,]+)\s*(?:rs\.?|inr|₹)", re.IGNORECASE),
    re.compile(r"(?:price|asking|expected)\s*[:=\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+)", re.IGNORECASE),
]

_LOCATION_PATTERN = re.compile(
    r"(?:location|city|loc|ship(?:ping)?\s*from)\s*[:=\-]\s*(.+?)(?:\n|<|$)",
    re.IGNORECASE,
)

# Hardware-related tags on TechEnclave
HARDWARE_TAGS = {"graphic-cards", "cpumobo", "storage-solutions", "pc-peripherals", "monitors"}


def _extract_price(html: str) -> float | None:
    """Extract first INR price from HTML post body."""
    # Strip HTML tags for cleaner matching
    text = re.sub(r"<[^>]+>", " ", html)
    for pattern in _PRICE_PATTERNS:
        match = pattern.search(text)
        if match:
            price_str = match.group(1).replace(",", "")
            try:
                price = float(price_str)
                if 500 <= price <= 5_000_000:
                    return price
            except ValueError:
                continue
    return None


_INDIAN_CITIES = {
    "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai",
    "kolkata", "pune", "ahmedabad", "jaipur", "lucknow", "chandigarh",
    "kochi", "indore", "nagpur", "coimbatore", "gurgaon", "noida",
    "ghaziabad", "thane", "navi mumbai", "vadodara", "surat", "bhopal",
    "patna", "vizag", "visakhapatnam", "mysore", "mangalore", "trivandrum",
}


def _extract_location(html: str) -> str | None:
    """Extract location from post body — label pattern then city scan."""
    text = re.sub(r"<[^>]+>", " ", html)
    match = _LOCATION_PATTERN.search(text)
    if match:
        loc = match.group(1).strip().rstrip(".,;")
        loc = re.sub(r"\s+", " ", loc)
        if len(loc) >= 3:
            return loc[:50]

    # Fallback: scan for known Indian city names
    text_lower = text.lower()
    for city in _INDIAN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", text_lower):
            return city.title()

    return None


def _strip_html(html: str) -> str:
    """Rough HTML to plaintext."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:2000]


class TechEnclaveScraper(BaseScraper):
    """Scrapes TechEnclave Trading Post > Classifieds via Discourse JSON API."""

    @property
    def source_name(self) -> str:
        return "techenclave"

    async def scrape(self, keywords: list[str] | None = None, max_pages: int = 3) -> list[Listing]:
        """Fetch listings from TechEnclave classifieds.

        If keywords are provided, uses Discourse search API.
        Otherwise, paginates through the classifieds category.
        """
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "DealHunter/0.1 (personal research tool)"},
            follow_redirects=True,
        ) as client:
            if keywords:
                topics = await self._search_topics(client, keywords, max_pages)
            else:
                topics = await self._fetch_category_topics(client, max_pages)

            listings = []
            for topic in topics:
                listing = await self._fetch_topic_detail(client, topic)
                if listing:
                    listings.append(listing)
                await asyncio.sleep(REQUEST_DELAY)

            self._log_results(len(listings))
            return listings

    async def _fetch_category_topics(
        self, client: httpx.AsyncClient, max_pages: int
    ) -> list[dict]:
        """Paginate through marketplace categories."""
        topics: list[dict] = []

        for cat_id, cat_slug in MARKETPLACE_CATEGORIES.items():
            for page in range(max_pages):
                url = f"{BASE_URL}/c/trading-post/{cat_slug}/{cat_id}.json"
                resp = await client.get(url, params={"page": page})
                if resp.status_code != 200:
                    logger.warning("TE %s page %d returned %d", cat_slug, page, resp.status_code)
                    break

                data = resp.json()
                page_topics = data.get("topic_list", {}).get("topics", [])
                if not page_topics:
                    break

                # Filter to hardware-related tags where possible
                for topic in page_topics:
                    tag_names = {t if isinstance(t, str) else t.get("name", "") for t in topic.get("tags", [])}
                    # Include if has hardware tag or no tags (might still be hardware)
                    if tag_names & HARDWARE_TAGS or not tag_names:
                        topics.append(topic)

                logger.debug("TE %s page %d: %d topics", cat_slug, page, len(page_topics))
                await asyncio.sleep(REQUEST_DELAY)

        return topics

    async def _search_topics(
        self, client: httpx.AsyncClient, keywords: list[str], max_pages: int
    ) -> list[dict]:
        """Search classifieds using Discourse search API."""
        topics: list[dict] = []
        for keyword in keywords[:5]:  # limit to 5 keywords
            query = f"{keyword} category:{DEFAULT_CATEGORY_ID}"
            resp = await client.get(
                f"{BASE_URL}/search.json",
                params={"q": query},
            )
            if resp.status_code != 200:
                logger.warning("TE search for '%s' returned %d", keyword, resp.status_code)
                continue

            data = resp.json()
            for topic in data.get("topics", []):
                topics.append(topic)

            await asyncio.sleep(REQUEST_DELAY)

        # Deduplicate by topic ID
        seen_ids: set[int] = set()
        unique: list[dict] = []
        for t in topics:
            if t["id"] not in seen_ids:
                seen_ids.add(t["id"])
                unique.append(t)
        return unique[:max_pages * 30]  # reasonable cap

    async def _fetch_topic_detail(
        self, client: httpx.AsyncClient, topic_summary: dict
    ) -> Listing | None:
        """Fetch full topic and build a Listing."""
        topic_id = topic_summary["id"]
        resp = await client.get(f"{BASE_URL}/t/{topic_id}.json")
        if resp.status_code != 200:
            logger.debug("TE topic %d returned %d", topic_id, resp.status_code)
            return None

        data = resp.json()
        posts = data.get("post_stream", {}).get("posts", [])
        if not posts:
            return None

        first_post = posts[0]
        body_html = first_post.get("cooked", "")
        body_text = _strip_html(body_html)
        title = data.get("title", "")

        price = _extract_price(body_html)
        location = _extract_location(body_html)

        posted_at = None
        created_str = data.get("created_at", "")
        if created_str:
            try:
                posted_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        slug = data.get("slug", "")
        url = f"{BASE_URL}/t/{slug}/{topic_id}"

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
        )
