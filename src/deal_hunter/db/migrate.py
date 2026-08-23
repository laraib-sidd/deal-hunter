"""Lightweight SQLite migrations for the v2 schema.

SQLModel.create_all() creates missing tables but does NOT add columns to already-existing
tables. The local DB predates v2 (sellers/watch_rules/watch_hits tables + new listing
columns), so we ALTER the existing `listings` table and let create_all handle new tables.

FK note: the `listings.seller_id -> sellers.id` FK is declared on the model, so it applies
to any NEW database created via create_all. SQLite cannot ALTER-ADD a foreign key to an
existing table without a destructive table-rebuild, so we deliberately do NOT rebuild the
existing DB here — that keeps this migration safe and non-destructive. Existing rows keep
the plain column; a full re-seed or new DB gets the FK.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect

logger = logging.getLogger(__name__)

# (column, type, default) — appended to `listings` if missing.
_LISTING_COLUMNS: list[tuple[str, str, str | None]] = [
    ("seller_id", "INTEGER", None),
    ("status", "VARCHAR", "'active'"),
    ("times_seen", "INTEGER", "1"),
    ("last_confirmed_at", "DATETIME", None),
]


def migrate(engine) -> None:
    """Add missing v2 columns to listings and the dedup index if absent (non-destructive)."""
    insp = inspect(engine)
    existing = {c["name"] for c in insp.get_columns("listings")}

    with engine.begin() as conn:
        for col, ctype, default in _LISTING_COLUMNS:
            if col not in existing:
                ddl = f'ALTER TABLE listings ADD COLUMN {col} {ctype}'
                if default:
                    ddl += f' DEFAULT {default}'
                conn.execute(__import__("sqlalchemy").text(ddl))
                logger.info("Migrated: listings.%s", col)

        idx_names = {ix["name"] for ix in insp.get_indexes("listings")}
        if "ix_listings_status" not in idx_names:
            conn.execute(__import__("sqlalchemy").text(
                "CREATE INDEX ix_listings_status ON listings (status)"
            ))

    logger.info("Migration complete")
