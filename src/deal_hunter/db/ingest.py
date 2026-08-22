"""IngestionService — the single writer for listings and sellers.

On each scrape it upserts sellers + listings, bumps freshness counters, and returns an
IngestionResult describing the delta (the new/reactivated listings are the trigger for
watch-matching and alerts).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlmodel import Session, select

from deal_hunter.db.models import Listing, Seller

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class IngestionResult:
    """Outcome of one ingest cycle."""

    new: list[Listing] = field(default_factory=list)
    seen: list[Listing] = field(default_factory=list)  # known, still active
    reactivated: list[Listing] = field(default_factory=list)  # was dead, re-listed
    duplicate_exact: int = 0  # duplicate (source, source_id) within this same batch

    @property
    def fresh(self) -> list[Listing]:
        """Newly surfaced listings — the alert trigger."""
        return self.new + self.reactivated


def _seller_key(source: str, listing: Listing) -> tuple[str, str] | None:
    """Derive a (source, source_key) for a listing's seller, if one is visible."""
    who = (listing.seller_name or "").strip()
    if not who:
        return None
    return source, who.lower()


class IngestionService:
    """Writes listings + sellers; returns the delta for downstream alerting."""

    def __init__(self, engine) -> None:
        self._engine = engine

    def ingest_batch(self, listings: list[Listing]) -> IngestionResult:
        result = IngestionResult()
        now = _now()

        # (source, source_key) -> Seller row currently in this session
        sellers: dict[tuple[str, str], Seller] = {}
        seen_keys: set[tuple[str, str]] = set()

        with Session(self._engine) as session:
            # 1) Upsert sellers
            seller_keys = {k for k in (_seller_key(ln.source, ln) for ln in listings) if k}
            for src, key in seller_keys:
                s = session.exec(
                    select(Seller).where(Seller.source == src, Seller.source_key == key)
                ).first()
                if s is None:
                    s = Seller(source=src, source_key=key, first_seen_at=now, last_seen_at=now)
                    session.add(s)
                    session.flush()  # assign id now so listings can reference it
                else:
                    s.last_seen_at = now
                sellers[(src, key)] = s

            # 2) listings
            for listing in listings:
                key = (listing.source, listing.source_id)
                if key in seen_keys:
                    result.duplicate_exact += 1
                    continue
                seen_keys.add(key)

                existing = session.exec(
                    select(Listing).where(Listing.source == key[0], Listing.source_id == key[1])
                ).first()

                s_key = _seller_key(listing.source, listing)
                if s_key is not None:
                    s = sellers[s_key]
                    listing.seller_id = s.id
                    if existing is None:
                        s.listing_count += 1

                if existing:
                    existing.times_seen += 1
                    existing.last_confirmed_at = now
                    if listing.price is not None and existing.price != listing.price:
                        existing.price = listing.price  # reflect price drops
                    if existing.status == "dead":
                        existing.status = "active"
                        result.reactivated.append(existing)
                    else:
                        result.seen.append(existing)
                    continue

                if not listing.fingerprint:
                    listing.fingerprint = Listing.compute_fingerprint(
                        listing.title, listing.price, listing.location
                    )
                listing.scraped_at = now
                listing.last_confirmed_at = now
                session.add(listing)
                result.new.append(listing)

            session.commit()

        logger.info(
            "Ingested: %d new, %d seen, %d reactivated, %d dup",
            len(result.new), len(result.seen), len(result.reactivated), result.duplicate_exact,
        )
        return result
