"""Score fresh listings and dispatch Telegram alerts once per offer."""

from __future__ import annotations

import logging

from deal_hunter.analysis.schemas import DealAnalysis
from deal_hunter.analysis.scorer import analyze_deal_async
from deal_hunter.config import AppConfig
from deal_hunter.db.ingest import mark_alerted, persist_scores
from deal_hunter.db.models import Listing
from deal_hunter.notifications.telegram import send_deal_alert, send_summary

logger = logging.getLogger(__name__)

_SKIP_CATEGORIES = frozenset({"wtb", "other"})
_MIN_RE_ALERT_DROP = 0.08
_ALERT_CAP = 5
_GOOD_VERDICTS = frozenset({"BUY", "NEGOTIATE"})


async def score_delta(
    engine,
    listings: list[Listing],
    *,
    ai_api_key: str = "",
) -> dict[int, DealAnalysis]:
    """Score only the given listings and persist analysis fields."""
    rows: list[tuple[int, DealAnalysis]] = []
    analyses: dict[int, DealAnalysis] = {}

    for listing in listings:
        if listing.price is None or listing.id is None:
            continue
        if listing.category in _SKIP_CATEGORIES:
            continue
        analysis = await analyze_deal_async(
            text=listing.title,
            asking_price=int(listing.price),
            location=listing.location or "",
            description=listing.description or "",
            ai_api_key=ai_api_key,
            engine=engine,
        )
        if analysis is None:
            continue
        rows.append((listing.id, analysis))
        analyses[listing.id] = analysis

    if rows:
        persist_scores(engine, rows)
    return analyses


def _drop_pct(old_price: float, new_price: float) -> float:
    if old_price <= 0:
        return 0.0
    return (old_price - new_price) / old_price


def decide_alerts(
    listings: list[Listing],
    analyses: dict[int, DealAnalysis],
    *,
    min_score: int,
    price_drops: list[tuple[Listing, float, float]] | None = None,
) -> list[tuple[Listing, DealAnalysis]]:
    """Pick up to five listings that merit a Telegram alert this cycle."""
    re_alert_ids: set[int] = set()
    for listing, old_price, new_price in price_drops or []:
        if listing.id is None:
            continue
        if _drop_pct(old_price, new_price) >= _MIN_RE_ALERT_DROP:
            re_alert_ids.add(listing.id)

    alerts: list[tuple[Listing, DealAnalysis]] = []
    for listing in listings:
        if listing.id is None:
            continue
        analysis = analyses.get(listing.id)
        if analysis is None:
            continue
        if analysis.verdict not in _GOOD_VERDICTS:
            continue
        if analysis.deal_score < min_score:
            continue
        if listing.alerted_at is not None and listing.id not in re_alert_ids:
            continue
        alerts.append((listing, analysis))

    alerts.sort(key=lambda pair: pair[1].deal_score, reverse=True)
    return alerts[:_ALERT_CAP]


async def dispatch(
    engine,
    config: AppConfig,
    alerts: list[tuple[Listing, DealAnalysis]],
) -> None:
    """Send listing alerts, then one summary, then mark rows alerted."""
    if not alerts:
        return
    if not config.telegram.enabled:
        return
    if not config.telegram.bot_token or not config.telegram.chat_id:
        return

    for listing, analysis in alerts:
        await send_deal_alert(
            bot_token=config.telegram.bot_token,
            chat_id=config.telegram.chat_id,
            analysis=analysis,
            listing_url=listing.url,
            posted_at=listing.posted_at,
        )

    await send_summary(
        bot_token=config.telegram.bot_token,
        chat_id=config.telegram.chat_id,
        total_scraped=len(alerts),
        deals_found=len(alerts),
        top_deals=[analysis for _, analysis in alerts],
    )

    listing_ids = [listing.id for listing, _ in alerts if listing.id is not None]
    mark_alerted(engine, listing_ids)
