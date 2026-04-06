"""SQLite engine and session management."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

from deal_hunter.db.models import Listing, PriceSnapshot

logger = logging.getLogger(__name__)


def get_engine(db_path: Path | None = None):
    """Create SQLite engine. Creates parent dirs and tables if needed."""
    path = db_path or (Path.home() / ".deal-hunter" / "deals.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", echo=False)
    SQLModel.metadata.create_all(engine)
    logger.info("Database ready at %s", path)
    return engine


def upsert_listings(engine, listings: list[Listing]) -> tuple[int, int]:
    """Insert listings, skipping duplicates within the same source.

    Returns (inserted, skipped) counts.
    """
    inserted = 0
    skipped = 0

    with Session(engine) as session:
        for listing in listings:
            # Check if source+source_id already exists
            source_val = listing.source
            source_id_val = listing.source_id
            existing = session.exec(
                select(Listing).where(
                    Listing.source == source_val,
                    Listing.source_id == source_id_val,
                )
            ).first()

            if existing:
                skipped += 1
                continue

            # Compute fingerprint if not set
            if not listing.fingerprint:
                listing.fingerprint = Listing.compute_fingerprint(
                    listing.title, listing.price, listing.location
                )

            session.add(listing)
            inserted += 1

        session.commit()

    logger.info("Upserted: %d inserted, %d skipped", inserted, skipped)
    return inserted, skipped


def search_listings(engine, query: str, limit: int = 50) -> list[Listing]:
    """Search stored listings by title substring."""
    with Session(engine) as session:
        results = session.exec(
            select(Listing)
            .where(Listing.title.contains(query))  # type: ignore[union-attr]
            .order_by(Listing.scraped_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        ).all()
        return list(results)


def get_recent_listings(
    engine, limit: int = 50, source: str | None = None, with_price: bool = False,
) -> list[Listing]:
    """Get most recently scraped listings."""
    with Session(engine) as session:
        stmt = select(Listing).order_by(Listing.scraped_at.desc()).limit(limit)  # type: ignore[union-attr]
        if source:
            stmt = stmt.where(Listing.source == source)
        if with_price:
            stmt = stmt.where(Listing.price.is_not(None))  # type: ignore[union-attr]
        return list(session.exec(stmt).all())


def record_price(engine, canonical_name: str, price: float, category: str = "", source: str = "", listing_url: str = "", location: str | None = None) -> None:
    """Record a price observation for trend tracking."""
    with Session(engine) as session:
        session.add(PriceSnapshot(
            canonical_name=canonical_name,
            category=category,
            source=source,
            price=price,
            listing_url=listing_url,
            location=location,
        ))
        session.commit()


def get_price_history(engine, canonical_name: str, limit: int = 50) -> list[PriceSnapshot]:
    """Get price history for a product, most recent first."""
    with Session(engine) as session:
        return list(session.exec(
            select(PriceSnapshot)
            .where(PriceSnapshot.canonical_name == canonical_name)
            .order_by(PriceSnapshot.observed_at.desc())  # type: ignore[union-attr]
            .limit(limit)
        ).all())


def get_price_summary(engine, canonical_name: str) -> dict | None:
    """Get price stats for a product: min, max, avg, count."""
    from sqlalchemy import func

    with Session(engine) as session:
        row = session.exec(
            select(
                func.count(PriceSnapshot.id).label("count"),
                func.min(PriceSnapshot.price).label("min_price"),
                func.max(PriceSnapshot.price).label("max_price"),
                func.avg(PriceSnapshot.price).label("avg_price"),
            ).where(PriceSnapshot.canonical_name == canonical_name)
        ).first()

        if not row or row[0] == 0:  # type: ignore[index]
            return None

        return {
            "count": row[0],  # type: ignore[index]
            "min_price": round(row[1]),  # type: ignore[index]
            "max_price": round(row[2]),  # type: ignore[index]
            "avg_price": round(row[3]),  # type: ignore[index]
        }
