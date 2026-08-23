"""Tests for run telemetry (repo_meta)."""
from __future__ import annotations

from datetime import UTC, datetime

from deal_hunter.db.engine import get_engine
from deal_hunter.db.repo_meta import last_run_summary, log_run, new_run_id


# simple in-memory-temp engine via tmp_path
def _engine(tmp_path):
    return get_engine(tmp_path / "t.db")


class TestRunTelemetry:
    def test_log_and_latest(self, tmp_path) -> None:
        e = _engine(tmp_path)
        run_id = new_run_id()
        log_run(e, {
            "run_id": run_id,
            "source": "reddit",
            "scraped": 42,
            "new": 5,
            "scored": 0,
            "failed": False,
            "duration_ms": 120,
            "circuit_state": "closed",
            "finished_at": datetime.now(UTC),
        })
        summary = last_run_summary(e)
        assert summary is not None
        assert summary["source"] == "reddit"
        assert summary["scraped"] == 42
        assert summary["run_id"] == run_id

    def test_no_runs_returns_none(self, tmp_path) -> None:
        e = _engine(tmp_path)
        assert last_run_summary(e) is None
