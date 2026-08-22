"""Reddit scraper — uses PRAW (sync) for hardware buy/sell posts."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import praw

from deal_hunter.db.models import Listing
from deal_hunter.scrapers.base import BaseScraper
from deal_hunter.scrapers.parsing import extract_location, extract_price

logger = logging.getLogger(__name__)

DEFAULT_SUBREDDITS = [
    "IndianGaming",          # 800K+ members, deal/sale posts mixed in
    "hwswapindia",           # Dedicated India hardware swap
    "hardwareswapindia",     # Another India swap sub
    "indiangamingdeals",     # Deals-focused
    "techdeals",             # General tech deals
    "IndianTechDeals",       # India tech deals
    "GameDealsIndia",        # India game/hardware deals
    "IndiaDealsExchange",    # India deals/coupons exchange
    "dealsforindia",         # 120K+ members, verified India deals
]

# Deal-focused subs where we skip the hardware requirement
DEAL_SUBREDDITS = {"IndiaDealsExchange", "dealsforindia"}

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

# Coupon/promo detection for deal-focused subreddits
_COUPON_PATTERNS = re.compile(
    r"\b(?:coupon|promo\s*code|discount|cashback|voucher|off|save|free|loot|"
    r"flight|ticket|hotel|booking|travel|makemytrip|easemytrip|cleartrip|"
    r"irctc|indigo|spicejet|airindia|goibibo|yatra|mmt)\b",
    re.IGNORECASE,
)


def _is_hardware_sale_post(title: str, body: str) -> bool:
    """Check if a post is a hardware buy/sell listing."""
    text = f"{title} {body}"
    return bool(_SALE_PATTERNS.search(text) and _HARDWARE_PATTERNS.search(text))


def _is_deal_post(title: str, body: str) -> bool:
    """Check if a post is a deal/coupon/offer — for deal-focused subreddits."""
    text = f"{title} {body}"
    return bool(_COUPON_PATTERNS.search(text) or _SALE_PATTERNS.search(text))


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
        import os

        # Netskope TLS proxy — trust org CA bundle so PRAW/requests doesn't fail SSL
        netskope_ca = "/private/etc/netskope/netskope-cert-bundle.pem"
        if os.path.exists(netskope_ca):
            os.environ.setdefault("REQUESTS_CA_BUNDLE", netskope_ca)
            os.environ.setdefault("SSL_CERT_FILE", netskope_ca)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._scrape_sync, keywords, max_pages)

    def _scrape_sync(self, keywords: list[str] | None, max_pages: int) -> list[Listing]:
        """Synchronous scraping with PRAW.

        Scrapes hardware subs and deal subs separately so high-volume deal subs
        don't crowd out the lower-volume hardware swap subs.
        """
        reddit = praw.Reddit(
            client_id=self._client_id,
            client_secret=self._client_secret,
            user_agent="DealHunter/0.1 (personal hardware deal finder)",
        )

        hardware_subs = [s for s in self._subreddits if s not in DEAL_SUBREDDITS]
        deal_subs = [s for s in self._subreddits if s in DEAL_SUBREDDITS]
        listings: list[Listing] = []

        # Hardware swap subs — scrape each individually at full depth
        hw_limit = max_pages * DEFAULT_LIMIT
        for sub in hardware_subs:
            logger.info("Scanning r/%s (limit=%d)", sub, hw_limit)
            try:
                for submission in reddit.subreddit(sub).new(limit=hw_limit):
                    title = submission.title
                    body = submission.selftext or ""
                    if not _is_hardware_sale_post(title, body):
                        continue
                    listings.append(self._build_listing(submission))
            except Exception as e:
                logger.warning("r/%s failed: %s", sub, e)

        # Deal subs — combined feed, looser filter
        if deal_subs:
            deal_limit = max_pages * DEFAULT_LIMIT
            multi = "+".join(deal_subs)
            logger.info("Scanning deal subs r/%s (limit=%d)", multi, deal_limit)
            try:
                for submission in reddit.subreddit(multi).new(limit=deal_limit):
                    title = submission.title
                    body = submission.selftext or ""
                    if not _is_deal_post(title, body):
                        continue
                    listings.append(self._build_listing(submission))
            except Exception as e:
                logger.warning("Deal subs failed: %s", e)

        self._log_results(len(listings))
        return listings

    def _build_listing(self, submission: object) -> Listing:
        """Build a Listing from a PRAW submission."""
        title = submission.title
        body = submission.selftext or ""
        full_text = f"{title} {body}"
        price = extract_price(full_text)
        location = extract_location(full_text)
        posted_at = datetime.fromtimestamp(submission.created_utc, tz=UTC)
        return Listing(
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
        )

