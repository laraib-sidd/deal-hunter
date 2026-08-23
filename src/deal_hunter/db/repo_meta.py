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
