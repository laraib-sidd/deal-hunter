"""Dashboard query repo — read-only aggregations for the web UI."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, col, select

from deal_hunter.db.models import Listing, Seller, WatchHit, WatchRule


def _now() -> datetime:
    return datetime.now(UTC)


def dash_overview(engine) -> dict:
    """Aggregate stats for the dashboard hero cards."""
    with Session(engine) as session:
        last24 = _now() - timedelta(hours=24)
        last24_new = session.exec(
            select(func.count(Listing.id)).where(col(Listing.scraped_at) >= last24)
        ).one()
        active = session.exec(
            select(func.count(Listing.id)).where(Listing.status == "active")
        ).one()
        active_deals = session.exec(
            select(func.count(Listing.id)).where(
                Listing.deal_score.is_not(None), Listing.deal_score >= 6
            )
        ).one()
        total_listings = session.exec(select(func.count(Listing.id))).one()
        sellers = session.exec(select(func.count(Seller.id))).one()
        watches = session.exec(
            select(func.count(WatchRule.id)).where(WatchRule.enabled == True)  # noqa: E712
        ).one()
        watch_hits = session.exec(select(func.count(WatchHit.id))).one()

    return {
        "scraped_24h": last24_new,
        "active": active,
        "active_deals": active_deals,
        "total": total_listings,
        "sellers": sellers,
        "watches": watches,
        "watch_hits": watch_hits,
    }


def recent_listings(engine, limit: int = 30, source: str | None = None) -> list[Listing]:
    with Session(engine) as session:
        stmt = select(Listing).order_by(col(Listing.scraped_at).desc()).limit(limit)
        if source:
            stmt = stmt.where(Listing.source == source)
        return list(session.exec(stmt).all())


def source_breakdown(engine) -> list[tuple[str, int]]:
    with Session(engine) as session:
        stmt = (
            select(Listing.source, func.count(Listing.id))
            .group_by(Listing.source)
            .order_by(func.count(Listing.id).desc())
        )
        return list(session.exec(stmt).all())


def top_canonical(engine, limit: int = 10) -> list[tuple[str, int]]:
    """Bar chart of the most-listed canonical products."""
    with Session(engine) as session:
        stmt = (
            select(Listing.canonical_name, func.count(Listing.id))
            .where(Listing.canonical_name.is_not(None))
            .group_by(Listing.canonical_name)
            .order_by(func.count(Listing.id).desc())
            .limit(limit)
        )
        return [(n or "—", c) for n, c in session.exec(stmt).all()]


def marketplace_listings(
    engine,
    category: str | None = None,
    verdict: str | None = None,
    source: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort: str = "newest",
    limit: int = 200,
) -> list[Listing]:
    """Filterable, sortable listing feed for the marketplace view."""
    with Session(engine) as session:
        stmt = select(Listing)
        if category and category != "all":
            stmt = stmt.where(Listing.category == category)
        if verdict:
            stmt = stmt.where(Listing.deal_verdict == verdict)
        if source:
            stmt = stmt.where(Listing.source == source)
        if min_price is not None:
            stmt = stmt.where(
                Listing.price.is_not(None), Listing.price >= min_price
            )
        if max_price is not None:
            stmt = stmt.where(
                Listing.price.is_not(None), Listing.price <= max_price
            )

        if sort == "price_low":
            stmt = stmt.order_by(Listing.price.asc())
        elif sort == "price_high":
            stmt = stmt.order_by(Listing.price.desc())
        elif sort == "score":
            stmt = stmt.order_by(col(Listing.deal_score).desc())
        else:
            stmt = stmt.order_by(col(Listing.scraped_at).desc())

        stmt = stmt.limit(limit)
        return list(session.exec(stmt).all())


def listings_for_canonical(engine, canonical_name: str, limit: int = 50) -> list[Listing]:
    with Session(engine) as session:
        stmt = (
            select(Listing)
            .where(Listing.canonical_name == canonical_name)
            .order_by(col(Listing.scraped_at).desc())
            .limit(limit)
        )
        return list(session.exec(stmt).all())


def get_watch_rules(engine) -> list[WatchRule]:
    with Session(engine) as session:
        return list(session.exec(select(WatchRule).order_by(WatchRule.created_at.desc())).all())  # type: ignore[union-attr]


def recent_watch_hits(engine, limit: int = 20) -> list[WatchHit]:
    with Session(engine) as session:
        return list(session.exec(select(WatchHit).order_by(WatchHit.score_at.desc()).limit(limit)).all())
