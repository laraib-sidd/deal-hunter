"""Live market baseline — compute rolling per-product market stats from price_history.

A "deal" should be judged against what OTHER sellers are actually asking, not just the
static depreciation model. We blend the two (config.weight_live).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, select

from deal_hunter.db.models import PriceSnapshot

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 60
DEFAULT_LIVE_WEIGHT = 0.5  # 0 = model only, 1 = live median only


class MarketStat:
    """A live per-product market summary."""

    def __init__(
        self,
        canonical_name: str,
        median: float | None,
        p25: float | None,
        p75: float | None,
        n: int,
        min_price: float | None,
        max_price: float | None,
        newest_observed_at: datetime | None = None,
    ) -> None:
        self.canonical_name = canonical_name
        self.median = median
        self.p25 = p25
        self.p75 = p75
        self.n = n
        self.min_price = min_price
        self.max_price = max_price
        self.newest_observed_at = newest_observed_at

    @property
    def sample_ok(self) -> bool:
        """Enough independent observations to trust the median."""
        return self.n >= 3

    def as_dict(self) -> dict:
        return {
            "canonical_name": self.canonical_name,
            "median": self.median,
            "p25": self.p25,
            "p75": self.p75,
            "n": self.n,
            "min_price": self.min_price,
            "max_price": self.max_price,
        }


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    f, c = int(k), int(k) + 1
    if c >= len(sorted_vals):
        c = len(sorted_vals) - 1
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def get_market_stats(
    engine,
    canonical_name: str | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_observations: int = 0,
) -> list[MarketStat]:
    """Compute market stats grouped by canonical_name.

    If canonical_name is given, returns 0 or 1 stats for just that product; otherwise returns
    stats for all products with at least min_observations in the window.
    """
    cutoff = datetime.now(UTC) - timedelta(days=window_days)

    with Session(engine) as session:
        stmt = select(PriceSnapshot.canonical_name, PriceSnapshot.price).where(
            col(PriceSnapshot.observed_at) >= cutoff
        )
        if canonical_name:
            stmt = stmt.where(PriceSnapshot.canonical_name == canonical_name)
        rows = session.exec(stmt).all()

    by_name: dict[str, list[float]] = {}
    for name, price in rows:
        if price is None:
            continue
        by_name.setdefault(name, []).append(float(price))

    stats: list[MarketStat] = []
    for name, prices in by_name.items():
        if len(prices) < max(min_observations, 1):
            continue
        prices.sort()
        stats.append(MarketStat(
            canonical_name=name,
            median=_percentile(prices, 0.5),
            p25=_percentile(prices, 0.25),
            p75=_percentile(prices, 0.75),
            n=len(prices),
            min_price=prices[0],
            max_price=prices[-1],
        ))

    if canonical_name:
        return [s for s in stats if s.canonical_name == canonical_name]
    stats.sort(key=lambda s: s.n, reverse=True)
    return stats


def get_market_stat(engine, canonical_name: str, window_days: int = DEFAULT_WINDOW_DAYS) -> MarketStat | None:
    """Convenience wrapper for a single product."""
    stats = get_market_stats(engine, canonical_name=canonical_name, window_days=window_days)
    return stats[0] if stats else None


def blend_fair_value(
    model_midpoint: float,
    live_midpoint: float | None,
    live_weight: float = DEFAULT_LIVE_WEIGHT,
) -> float:
    """Blend the static depreciation model with the live median."""
    if live_midpoint is None or live_midpoint <= 0:
        return float(model_midpoint)
    return model_midpoint * (1 - live_weight) + live_midpoint * live_weight
