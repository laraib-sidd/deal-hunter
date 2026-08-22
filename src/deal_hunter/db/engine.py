"""SQLite engine + session factory.

This module is intentionally minimal (SRP): it only builds/migrates the engine and
re-exports the repo helpers so existing `from deal_hunter.db.engine import ...` imports
keep working. Listing persistence lives in `repo_listings`, price history in
`repo_prices`, and dashboard aggregations in `repo_dash`.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import SQLModel, create_engine

from deal_hunter.db.repo_listings import (
    get_recent_listings,
    search_listings,
    upsert_listings,
)
from deal_hunter.db.repo_prices import (
    get_price_history,
    get_price_summary,
    record_price,
)

logger = logging.getLogger(__name__)

__all__ = [
    "get_engine",
    # re-exported listing repos
    "upsert_listings",
    "search_listings",
    "get_recent_listings",
    # re-exported price repos
    "record_price",
    "get_price_history",
    "get_price_summary",
]


def get_engine(db_path: Path | None = None):
    """Create SQLite engine. Creates parent dirs and tables if needed."""
    path = db_path or (Path.home() / ".deal-hunter" / "deals.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", echo=False)
    SQLModel.metadata.create_all(engine)
    # v2 columns on pre-existing tables (sellers, watch_rules, watch_hits auto-created)
    try:
        from deal_hunter.db.migrate import migrate

        migrate(engine)
    except Exception:  # pragma: no cover - migration is best-effort on old DBs
        logger.exception("Migration failed (continuing with base tables)")
    logger.info("Database ready at %s", path)
    return engine
