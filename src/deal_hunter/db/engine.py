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
from deal_hunter.db.repo_meta import RunLog  # noqa: F401  (registers run_logs metadata)
from deal_hunter.db.repo_prices import (
    get_price_history,
    get_price_summary,
    record_price,
    record_prices,
)

# Re-exported repo helpers so existing `from deal_hunter.db.engine import X` keeps working.
__all__ = [
    "get_engine",
    "upsert_listings",
    "search_listings",
    "get_recent_listings",
    "record_price",
    "record_prices",
    "get_price_history",
    "get_price_summary",
]

logger = logging.getLogger(__name__)

# Single shared engine per process (12-Factor IV: backing service is a shared dependency).
_ENGINE_CACHE: dict[str, object] = {}


def get_engine(db_path: Path | None = None):
    """Create (or return the cached) SQLite engine for the given path.

    The engine is cached per resolved path so the whole process shares one connection
    pool / handle to the backing store, avoiding "database is locked" and divergent
    handles. Parent dirs + tables are created on first use.
    """
    path = db_path or (Path.home() / ".deal-hunter" / "deals.db")
    key = str(path.resolve())

    if key in _ENGINE_CACHE:
        return _ENGINE_CACHE[key]

    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", echo=False)
    SQLModel.metadata.create_all(engine)
    # v2 columns on pre-existing tables (sellers, watch_rules, watch_hits auto-created)
    try:
        from deal_hunter.db.migrate import migrate

        migrate(engine)
    except Exception:  # pragma: no cover - migration is best-effort on old DBs
        logger.exception("Migration failed (continuing with base tables)")

    _ENGINE_CACHE[key] = engine
    logger.info("Database ready at %s", path)
    return engine
