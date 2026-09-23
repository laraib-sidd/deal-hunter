"""Shared parsing helpers for scrapers and the scorer.

DRY: price extraction, location extraction, HTML-to-text, and the Indian city list
were duplicated across reddit.py, techenclave.py, and scorer.py. This module is the
single source of truth for all of them.
"""
from __future__ import annotations

import re

# Standard INR price patterns — shared by all sources
PRICE_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+)", re.IGNORECASE),
    re.compile(r"([\d,]+)\s*(?:rs\.?|inr|₹)", re.IGNORECASE),
    re.compile(r"(?:price|asking|expected)\s*[:=\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+)", re.IGNORECASE),
]

# "15k" / "25K" style prices common in Indian posts
K_PRICE_PATTERN: re.Pattern = re.compile(r"\b(\d{1,3})k\b", re.IGNORECASE)

MIN_PRICE = 500.0
MAX_PRICE = 5_000_000.0

# Location label patterns
_LOCATION_PATTERN = re.compile(
    r"(?:location|city|loc|based\s+in|ship(?:ping)?\s+from)\s*[:=\-]\s*([A-Za-z][A-Za-z ]{2,25})",
    re.IGNORECASE,
)

# Common Indian cities — shared by all sources
INDIAN_CITIES: frozenset[str] = frozenset({
    "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai",
    "kolkata", "pune", "ahmedabad", "jaipur", "lucknow", "chandigarh",
    "kochi", "indore", "nagpur", "coimbatore", "gurgaon", "noida",
    "ghaziabad", "thane", "navi mumbai", "vadodara", "surat", "bhopal",
    "patna", "vizag", "visakhapatnam", "mysore", "mangalore", "trivandrum",
})


def strip_html(html: str, max_len: int = 2000) -> str:
    """Rough HTML-to-plaintext, collapsed whitespace, truncated."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:max_len]


def extract_price(text: str) -> float | None:
    """Extract the first plausible INR price from text.

    Works on either plaintext or HTML (HTML tags are stripped first).
    Returns None if no sensible price is found.
    """
    plain = strip_html(text, max_len=100_000) if "<" in text else text

    # Standard INR patterns first
    for pattern in PRICE_PATTERNS:
        match = pattern.search(plain)
        if match:
            price_str = match.group(1).replace(",", "")
            try:
                price = float(price_str)
                if MIN_PRICE <= price <= MAX_PRICE:
                    return price
            except ValueError:
                continue

    # "15k" / "25K" style (multiply by 1000)
    k_match = K_PRICE_PATTERN.search(plain)
    if k_match:
        try:
            price = int(k_match.group(1)) * 1000
            if 1000 <= price <= 500_000:
                return float(price)
        except ValueError:
            pass

    return None


def extract_location(text: str) -> str | None:
    """Extract location — try label pattern first, then city-name scan.

    Works on plaintext or HTML.
    """
    plain = strip_html(text, max_len=100_000) if "<" in text else text

    match = _LOCATION_PATTERN.search(plain)
    if match:
        loc = match.group(1).strip().rstrip(".,;")
        if len(loc) >= 3:
            return loc[:50]

    # Fallback: scan for known Indian city names
    text_lower = plain.lower()
    for city in INDIAN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", text_lower):
            return city.title()

    return None

# --- intent / spam classification (canonical; reddit.py copies removed in slice C) ---

_WTB_PATTERNS = re.compile(
    r"(?:"
    r"\b(?:wtb|want\s+to\s+buy|buying|looking\s+for|need\s+(?:a|an|to\s+buy))\b"
    r"|\[wtb\]|\[w\]"
    r")",
    re.IGNORECASE,
)

_COUPON_PATTERNS = re.compile(
    r"\b(?:coupon|promo\s*code|discount|cashback|voucher|off|save|free|loot|"
    r"flight|ticket|hotel|booking|travel|makemytrip|easemytrip|cleartrip|"
    r"irctc|indigo|spicejet|airindia|goibibo|yatra|mmt)\b",
    re.IGNORECASE,
)

_SPAM_PATTERNS = re.compile(
    r"(?:\b\d{1,3}(?:%|\s)?\s*upi\b"
    r"\b|\bg[i]?ft\s*card\b|\bpaytm\s*cash\b"
    r"|amazon\s*(?:pay)?\s*gc\b|flipkart\s*gc\b"
    r"|\b\w+\s*gc\b\s+\[w\]|\b\[w\]\s+.*?\bupi\b)",
    re.IGNORECASE,
)

_WTB_CATEGORY_HINTS = frozenset({"wtb", "looking-to-buy", "18"})


def is_spam_post(title: str, body: str) -> bool:
    """True if the post is finance/trade/UPI spam, not a hardware listing."""
    text = f"{title} {body}"
    return bool(_SPAM_PATTERNS.search(text))


def is_coupon_post(title: str, body: str) -> bool:
    """True if the post is a coupon/promo/travel offer rather than a sale listing."""
    text = f"{title} {body}"
    return bool(_COUPON_PATTERNS.search(text))


def classify_intent(title: str, body: str, category_hint: str | None = None) -> str:
    """Classify listing intent as sell, wtb (want-to-buy), or other (spam/coupon/noise)."""
    if is_spam_post(title, body) or is_coupon_post(title, body):
        return "other"
    hint = (category_hint or "").strip().lower()
    if hint in _WTB_CATEGORY_HINTS:
        return "wtb"
    text = f"{title} {body}"
    if _WTB_PATTERNS.search(text):
        return "wtb"
    return "sell"

