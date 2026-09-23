"""Run telemetry — per-cycle scrape summary for observability.

Each scrape cycle emits one row: source, counts, duration, circuit state. The dashboard's
/health reads the latest for a health pulse.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import Field, Session, SQLModel, select

logger = logging.getLogger(__name__)


class RunLog(SQLModel, table=True):
    __tablename__ = "run_logs"

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    source: str = Field(index=True)
    scraped: int = 0
    new: int = 0
    scored: int = 0
    failed: bool = False
    duration_ms: int = 0
    circuit_state: str = "closed"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


def new_run_id() -> str:
    return uuid4().hex[:12]


def log_run(engine, run: dict) -> None:
    """Insert one run telemetry row (reuses the shared engine's session)."""
    with Session(engine) as session:
        session.add(RunLog(**run))
        session.commit()


def log_run_batch(engine, runs: list[dict]) -> None:
    """Insert many run telemetry rows in one transaction."""
    with Session(engine) as session:
        session.add_all(RunLog(**r) for r in runs)
        session.commit()


def latest_runs(engine, limit: int = 20) -> list[RunLog]:
    with Session(engine) as session:
        return list(
            session.exec(
                select(RunLog).order_by(RunLog.started_at.desc()).limit(limit)  # type: ignore[union-attr]
            ).all()
        )


def last_run_summary(engine) -> dict | None:
    """Latest run per the most recent started_at — used by /health."""
    with Session(engine) as session:
        row = session.exec(
            select(RunLog).order_by(RunLog.started_at.desc())
        ).first()
        if row is None:
            return None
        return {
            "run_id": row.run_id,
            "source": row.source,
            "scraped": row.scraped,
            "new": row.new,
            "scored": row.scored,
            "failed": row.failed,
            "circuit_state": row.circuit_state,
            "duration_ms": row.duration_ms,
            "started_at": row.started_at,
        }

class ScrapeCursor(SQLModel, table=True):
    """Incremental scrape watermark per source bucket (category id or subreddit name)."""

    __tablename__ = "scrape_cursors"

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    bucket: str = Field(index=True)
    cursor_id: str
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def load_known_ids(engine, source: str) -> set[str]:
    """Union of stored cursor ids for a source — passed to scrapers as known_ids."""
    with Session(engine) as session:
        rows = session.exec(
            select(ScrapeCursor.cursor_id).where(ScrapeCursor.source == source)
        ).all()
        return set(rows)


def load_cursors(engine, source: str) -> dict[str, str]:
    """Return bucket -> cursor_id for a source."""
    with Session(engine) as session:
        rows = session.exec(select(ScrapeCursor).where(ScrapeCursor.source == source)).all()
        return {row.bucket: row.cursor_id for row in rows}


def set_cursor(engine, source: str, bucket: str, cursor_id: str) -> None:
    """Upsert one (source, bucket) cursor."""
    with Session(engine) as session:
        row = session.exec(
            select(ScrapeCursor).where(
                ScrapeCursor.source == source,
                ScrapeCursor.bucket == bucket,
            )
        ).first()
        now = datetime.now(UTC)
        if row is None:
            session.add(ScrapeCursor(source=source, bucket=bucket, cursor_id=cursor_id, updated_at=now))
        elif _cursor_is_newer(cursor_id, row.cursor_id):
            row.cursor_id = cursor_id
            row.updated_at = now
            session.add(row)
        session.commit()


def _cursor_sort_key(cursor_id: str) -> tuple[int, int | str]:
    """Sort key for monotonic platform ids (decimal discourse, base36 reddit)."""
    try:
        return (0, int(cursor_id))
    except ValueError:
        try:
            return (1, int(cursor_id, 36))
        except ValueError:
            return (2, cursor_id)


def _cursor_is_newer(candidate: str, existing: str) -> bool:
    """True when candidate sorts after existing (monotonic ids)."""
    return _cursor_sort_key(candidate) > _cursor_sort_key(existing)


def _listing_bucket(listing) -> str:
    """Derive scrape bucket from a listing (subreddit slug or category id)."""
    if listing.source == "reddit":
        import re

        match = re.search(r"reddit\.com/r/([^/]+)/", listing.url)
        if match:
            return match.group(1)
    if listing.source == "techenclave" and listing.category:
        cat = str(listing.category)
        if cat.isdigit():
            return cat
    return "_default"


def advance_cursors(engine, source: str, listings: list) -> None:
    """After a successful source run, move each bucket cursor to its newest reported id."""
    if not listings:
        return
    by_bucket: dict[str, list] = {}
    for listing in listings:
        bucket = _listing_bucket(listing)
        by_bucket.setdefault(bucket, []).append(listing)

    for bucket, bucket_listings in by_bucket.items():
        newest = max(bucket_listings, key=lambda item: _cursor_sort_key(item.source_id), default=None)
        if newest is not None:
            set_cursor(engine, source, bucket, newest.source_id)

