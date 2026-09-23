"""Database models for storing scraped listings."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class Listing(SQLModel, table=True):
    """A hardware listing scraped from any source."""

    __tablename__ = "listings"
    __table_args__ = (
        Index("uq_listing_source_item", "source", "source_id", unique=True),
    )

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
    seller_id: int | None = Field(default=None, index=True, foreign_key="sellers.id")
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
    alerted_at: datetime | None = Field(default=None, index=True)

    @staticmethod
    def compute_fingerprint(title: str, price: float | None, location: str | None) -> str:
        """Compute a dedup fingerprint from normalized title and location.

        ``price`` is kept in the signature for backward compatibility with existing
        call sites but is not included in the hash; offer identity is ``(source, source_id)``.
        """
        normalized = f"{title.lower().strip()}|{(location or '').lower().strip()}"
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


class AiCache(SQLModel, table=True):
    """Cache of AI-normalize results keyed by listing fingerprint (no re-billing)."""

    __tablename__ = "ai_cache"

    id: int | None = Field(default=None, primary_key=True)
    fingerprint: str = Field(index=True, unique=True)
    result_json: str  # serialized HardwareMatch-equivalent
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ============================ Catalog (M4) ============================


class Product(SQLModel, table=True):
    """A hardware product in the scalable catalog (replaces JSON hardware_db as truth)."""

    __tablename__ = "products"

    id: int | None = Field(default=None, primary_key=True)
    hardware_id: str = Field(index=True, unique=True)  # stable slug: "nvidia-rtx-3080"
    canonical_name: str = Field(index=True)
    category: str = Field(index=True)  # gpu|cpu|ram|ssd|monitor|motherboard|psu|laptop|...
    brand: str = ""
    series: str = ""
    generation: str = ""
    release_date: str | None = None  # "YYYY-MM"
    msrp_inr: int | None = None
    source: str = Field(default="curated")  # curated | bundled | ai
    confidence: float = Field(default=1.0)
    specs_json: str = ""  # JSON: {vram_gb, tdp_w, cores, socket, mining_popular, ...}
    mining_popular: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProductAlias(SQLModel, table=True):
    """An alias token -> product (the hot path for matching many listing titles)."""

    __tablename__ = "product_aliases"

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.id", index=True)
    alias: str = Field(index=True)  # lowercased: "rtx 3080", "3080", ...
    confidence: float = Field(default=1.0)
    source: str = Field(default="curated")


class ProductSpec(SQLModel, table=True):
    """Optional key/value spec variants for a product."""

    __tablename__ = "product_specs"

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.id", index=True)
    key: str = Field(index=True)
    value: str = ""


class MsrpHistory(SQLModel, table=True):
    """MSRP changes over time (currency moves / official drops)."""

    __tablename__ = "msrp_history"

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.id", index=True)
    msrp_inr: int
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = ""


class CityTier(SQLModel, table=True):
    """Indian city -> tier, replacing the hardcoded dict in JSON."""

    __tablename__ = "city_tiers"

    id: int | None = Field(default=None, primary_key=True)
    city: str = Field(index=True, unique=True)
    tier: int = Field(default=2)
