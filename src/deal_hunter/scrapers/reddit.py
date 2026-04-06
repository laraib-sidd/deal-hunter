"""Reddit scraper — uses PRAW (sync) for hardware buy/sell posts."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import praw

from deal_hunter.db.models import Listing
from deal_hunter.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

DEFAULT_SUBREDDITS = [
    "IndianGaming",          # 800K+ members, deal/sale posts mixed in
    "hwswapindia",           # Dedicated India hardware swap
    "hardwareswapindia",     # Another India swap sub
    "indiangamingdeals",     # Deals-focused
    "techdeals",             # General tech deals
    "IndianTechDeals",       # India tech deals
    "GameDealsIndia",        # India game/hardware deals
]
DEFAULT_LIMIT = 200  # posts per subreddit batch

# Sale intent detection — broader to catch more listing styles
_SALE_PATTERNS = re.compile(
    r"(?:"
    r"\b(?:sell(?:ing)?|sold|wts|fs|for\s+sale|wtb|want\s+to\s+buy|buying|looking\s+for)\b"
    r"|\[h\]|\[w\]|\[fs\]|\[wts\]|\[wtb\]"
    r"|\b(?:deal|offer|price|asking|budget|under\s+\d)"
    r"|\b(?:₹|rs\.?|inr)\s*\d"  # any price mention = likely a sale
    r")",
    re.IGNORECASE,
)

# Hardware keywords — expanded
_HARDWARE_PATTERNS = re.compile(
    r"\b(?:gpu|cpu|ram|ssd|hdd|nvme|motherboard|mobo|psu|monitor|keyboard|mouse|cabinet|case|"
    r"rtx|gtx|rx\s?\d{3,4}|ryzen|intel|amd|nvidia|geforce|radeon|"
    r"headphone|headset|earphone|speaker|webcam|controller|joystick|"
    r"router|wifi|ups|cooler|aio|fan|"
    r"laptop|thinkpad|macbook|asus|msi|dell|hp|lenovo|acer|"
    r"iphone|ipad|pixel|samsung|oneplus|realme|poco|"
    r"gaming\s+(?:pc|chair|desk)|build|rig|setup)\b",
    re.IGNORECASE,
)

# Price extraction
_PRICE_PATTERNS = [
    re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+)", re.IGNORECASE),
    re.compile(r"([\d,]+)\s*(?:rs\.?|inr|₹)", re.IGNORECASE),
    re.compile(r"(?:price|asking|expected)\s*[:=\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+)", re.IGNORECASE),
]

# "15k" / "25K" style prices common in Indian posts
_K_PRICE_PATTERN = re.compile(r"\b(\d{1,3})k\b", re.IGNORECASE)

_LOCATION_PATTERN = re.compile(
    r"(?:location|city|loc|based\s+in|ship(?:ping)?\s+from)\s*[:=\-]\s*([A-Za-z][A-Za-z ]{2,25})",
    re.IGNORECASE,
)

# Common Indian cities for direct mention detection in titles
_INDIAN_CITIES = {
    "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai",
    "kolkata", "pune", "ahmedabad", "jaipur", "lucknow", "chandigarh",
    "kochi", "indore", "nagpur", "coimbatore", "gurgaon", "noida",
    "ghaziabad", "thane", "navi mumbai", "vadodara", "surat", "bhopal",
    "patna", "vizag", "visakhapatnam", "mysore", "mangalore", "trivandrum",
}


def _extract_location(text: str) -> str | None:
    """Extract location — try label pattern first, then city name scan."""
    match = _LOCATION_PATTERN.search(text)
    if match:
        loc = match.group(1).strip().rstrip(".,;")
        if len(loc) >= 3:
            return loc[:50]

    # Fallback: scan for known Indian city names
    text_lower = text.lower()
    for city in _INDIAN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", text_lower):
            return city.title()

    return None


def _is_hardware_sale_post(title: str, body: str) -> bool:
    """Check if a post is a hardware buy/sell listing."""
    text = f"{title} {body}"
    return bool(_SALE_PATTERNS.search(text) and _HARDWARE_PATTERNS.search(text))


def _extract_price(text: str) -> float | None:
    # Standard INR patterns first
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

    # "15k" / "25K" style (multiply by 1000)
    k_match = _K_PRICE_PATTERN.search(text)
    if k_match:
        try:
            price = int(k_match.group(1)) * 1000
            if 1000 <= price <= 500_000:
                return float(price)
        except ValueError:
            pass

    return None


class RedditScraper(BaseScraper):
    """Scrapes Reddit for hardware buy/sell posts using PRAW."""

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        subreddits: list[str] | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._subreddits = subreddits or DEFAULT_SUBREDDITS

    @property
    def source_name(self) -> str:
        return "reddit"

    async def scrape(self, keywords: list[str] | None = None, max_pages: int = 3) -> list[Listing]:
        """Fetch hardware buy/sell posts from configured subreddits.

        PRAW is synchronous, so this runs in an executor to not block the event loop.
        """
        if not self._client_id or not self._client_secret:
            logger.warning("Reddit API credentials not configured — skipping Reddit scraper")
            return []

        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._scrape_sync, keywords, max_pages)

    def _scrape_sync(self, keywords: list[str] | None, max_pages: int) -> list[Listing]:
        """Synchronous scraping with PRAW."""
        reddit = praw.Reddit(
            client_id=self._client_id,
            client_secret=self._client_secret,
            user_agent="DealHunter/0.1 (personal hardware deal finder)",
        )

        limit = max_pages * DEFAULT_LIMIT
        multi = "+".join(self._subreddits)
        listings: list[Listing] = []

        logger.info("Scanning r/%s (limit=%d)", multi, limit)

        for submission in reddit.subreddit(multi).new(limit=limit):
            title = submission.title
            body = submission.selftext or ""

            if not _is_hardware_sale_post(title, body):
                continue

            full_text = f"{title} {body}"
            price = _extract_price(full_text)
            location = _extract_location(full_text)

            posted_at = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)

            listings.append(Listing(
                source="reddit",
                source_id=submission.id,
                fingerprint=Listing.compute_fingerprint(title, price, location),
                url=f"https://reddit.com{submission.permalink}",
                title=title,
                description=body[:2000] if body else None,
                price=price,
                location=location,
                seller_name=str(submission.author) if submission.author else None,
                posted_at=posted_at,
            ))

        self._log_results(len(listings))
        return listings
