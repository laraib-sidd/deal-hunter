"""AI-result cache + per-run call guardrail.

M5: avoids re-billing Groq for the same listing (cache by fingerprint) and enforces
a `max_ai_calls_per_run` so a large batch can't blow the free-tier quota.
"""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from deal_hunter.db.models import AiCache

logger = logging.getLogger(__name__)


class AiBudget:
    """Tracks AI calls within one run and stops once a cap is hit."""

    def __init__(self, max_calls: int = 500) -> None:
        self._max_calls = max_calls
        self._used = 0

    @property
    def remaining(self) -> int:
        return max(0, self._max_calls - self._used)

    def allow(self) -> bool:
        """Whether another AI call is permitted this run."""
        if self._used >= self._max_calls:
            return False
        self._used += 1
        return True


def cache_get(engine, fingerprint: str) -> str | None:
    """Return cached serialized result for a fingerprint, or None."""
    with Session(engine) as session:
        row = session.exec(
            select(AiCache).where(AiCache.fingerprint == fingerprint)
        ).first()
        return row.result_json if row else None


def cache_put(engine, fingerprint: str, result_json: str) -> None:
    with Session(engine) as session:
        existing = session.exec(
            select(AiCache).where(AiCache.fingerprint == fingerprint)
        ).first()
        if existing:
            existing.result_json = result_json
        else:
            session.add(AiCache(fingerprint=fingerprint, result_json=result_json))
        session.commit()
