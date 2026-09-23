"""End-to-end ingest → score → alert-once cycle."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlmodel import Session, select

from deal_hunter.cli import _process_ingest_result
from deal_hunter.config import AppConfig, TelegramConfig
from deal_hunter.db.engine import get_engine
from deal_hunter.db.ingest import IngestionService
from deal_hunter.db.models import Listing


def _listing(
    source: str,
    source_id: str,
    title: str = "RTX 3060 12GB",
    price: float = 5000.0,
    category: str = "gpu",
) -> Listing:
    return Listing(
        source=source,
        source_id=source_id,
        fingerprint=Listing.compute_fingerprint(title, price, None),
        url=f"https://example.com/{source}/{source_id}",
        title=title,
        price=price,
        category=category,
        posted_at=datetime.now(UTC),
    )


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        db_path=tmp_path / "cycle.db",
        telegram=TelegramConfig(enabled=True, bot_token="tok", chat_id="1"),
    )


def _reload(engine, source_id: str) -> Listing:
    with Session(engine) as session:
        row = session.exec(select(Listing).where(Listing.source_id == source_id)).first()
        assert row is not None
        return row


class TestIngestScoreAlertCycle:
    @pytest.mark.asyncio
    async def test_alert_once_then_realert_on_eight_percent_drop(
        self, tmp_path, httpx_mock
    ) -> None:
        config = _config(tmp_path)
        engine = get_engine(config.db_path)
        svc = IngestionService(engine)

        initial = [
            _listing("reddit", "r1"),
            _listing("techenclave", "t1", title="RTX 3060 12GB", price=5200.0),
        ]
        first = svc.ingest_batch(initial)

        for _ in range(3):
            httpx_mock.add_response(
                url="https://api.telegram.org/bottok/sendMessage",
                json={"ok": True, "result": {"message_id": 1}},
            )

        await _process_ingest_result(
            engine,
            config,
            first,
            min_score=6,
            ai=False,
            notify=True,
        )
        assert len(httpx_mock.get_requests()) == 3

        second_batch = [
            _listing("reddit", "r1", price=5000.0),
            _listing("techenclave", "t1", title="RTX 3060 12GB", price=5200.0),
        ]
        second = svc.ingest_batch(second_batch)

        await _process_ingest_result(
            engine,
            config,
            second,
            min_score=6,
            ai=False,
            notify=True,
        )
        assert len(httpx_mock.get_requests()) == 3

        reddit = _reload(engine, "r1")
        assert reddit.alerted_at is not None
        assert reddit.deal_score is not None

        dropped = _listing("reddit", "r1", price=4500.0)
        third = svc.ingest_batch([dropped])
        assert len(third.price_drops) == 1

        for _ in range(2):
            httpx_mock.add_response(
                url="https://api.telegram.org/bottok/sendMessage",
                json={"ok": True, "result": {"message_id": 2}},
            )

        await _process_ingest_result(
            engine,
            config,
            third,
            min_score=6,
            ai=False,
            notify=True,
        )
        assert len(httpx_mock.get_requests()) == 5
