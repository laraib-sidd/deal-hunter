"""Database models for storing scraped listings."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Listing(SQLModel, table=True):
    """A hardware listing scraped from any source."""

    __tablename__ = "listings"

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)  # "techenclave" | "reddit" | "olx"
    source_id: str  # platform-specific unique ID
    fingerprint: str = Field(index=True)  # cross-source dedup
    url: str
    title: str
    description: str | None = None
    price: float | None = None
    currency: str = "INR"
    category: str = "other"
    canonical_name: str | None = None
    location: str | None = None
    seller_name: str | None = None
    seller_id: int | None = Field(default=None, index=True)  # FK -> sellers.id
    posted_at: datetime | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Deal analysis (populated later)
    deal_score: float | None = None
    deal_verdict: str | None = None
    deal_reason: str | None = None
    red_flags_json: str | None = None  # JSON serialized list

    seen: bool = False

    # v2 lifecycle + freshness
    status: str = Field(default="active", index=True)  # active | stale | dead | suppressed
    times_seen: int = Field(default=1)
    last_confirmed_at: datetime | None = Field(default=None, index=True)

    @staticmethod
    def compute_fingerprint(title: str, price: float | None, location: str | None) -> str:
        """Compute a dedup fingerprint from normalized fields."""
        normalized = f"{title.lower().strip()}|{price}|{(location or '').lower().strip()}"
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]


class PriceSnapshot(SQLModel, table=True):
    """Historical price observation for a product across sources."""

    __tablename__ = "price_history"

    id: int | None = Field(default=None, primary_key=True)
    canonical_name: str = Field(index=True)
    category: str = ""
    source: str = ""
    price: float
    listing_url: str = ""
    location: str | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Seller(SQLModel, table=True):
    """A seller/exposer of listings across sources."""

    __tablename__ = "sellers"

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    source_key: str = Field(index=True)  # platform-specific seller id / username
    display_name: str | None = None
    url: str | None = None

    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    listing_count: int = Field(default=0)
    flagged_count: int = Field(default=0)
    is_suspect: bool = Field(default=False)
    notes: str | None = None


class WatchRule(SQLModel, table=True):
    """Persistent user buy-intent rule."""

    __tablename__ = "watch_rules"

    id: int | None = Field(default=None, primary_key=True)
    label: str = ""
    enabled: bool = Field(default=True)
    kind: str = "query"  # query | price
    query: str = Field(index=True)
    category: str | None = None
    min_score: int | None = Field(default=None)
    max_price: float | None = Field(default=None, index=True)
    locations: str | None = None  # JSON list
    alert_on_newest: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WatchHit(SQLModel, table=True):
    """A rule matched a listing; used for alert de-duplication."""

    __tablename__ = "watch_hits"

    id: int | None = Field(default=None, primary_key=True)
    rule_id: int = Field(index=True)
    listing_id: int = Field(index=True)
    score_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    alerted_at: datetime | None = Field(default=None, index=True)
