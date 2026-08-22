"""Price-history persistence.

SRP: price snapshot read/write moved out of `engine.py`. Existing
`deal_hunter.db.engine` imports still work (see re-exports there).
"""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from deal_hunter.db.models import PriceSnapshot

logger = logging.getLogger(__name__)


def record_price(
    engine,
    canonical_name: str,
    price: float,
    category: str = "",
    source: str = "",
    listing_url: str = "",
    location: str | None = None,
) -> None:
    """Record a single price observation for trend tracking."""
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


def record_prices(engine, snapshots: list[PriceSnapshot]) -> None:
    """Record many price observations in a single transaction (batch)."""
    with Session(engine) as session:
        session.add_all(snapshots)
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
