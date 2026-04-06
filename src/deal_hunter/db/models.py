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
    posted_at: datetime | None = None
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Deal analysis (populated later)
    deal_score: float | None = None
    deal_verdict: str | None = None
    deal_reason: str | None = None
    red_flags_json: str | None = None  # JSON serialized list

    seen: bool = False

    @staticmethod
    def compute_fingerprint(title: str, price: float | None, location: str | None) -> str:
        """Compute a dedup fingerprint from normalized fields."""
        normalized = f"{title.lower().strip()}|{price}|{(location or '').lower().strip()}"
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]
