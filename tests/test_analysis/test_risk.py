"""Tests for the layered risk aggregator (M5)."""
from __future__ import annotations

from deal_hunter.analysis.risk import aggregate_risk
from deal_hunter.analysis.schemas import RedFlag


def _flag(sev: str) -> RedFlag:
    return RedFlag(flag_type="test", severity=sev, detail="x")


class TestRiskAggregator:
    def test_any_critical_is_critical(self) -> None:
        r = aggregate_risk([_flag("high"), _flag("critical")])
        assert r.level == "critical"

    def test_high_count_raises_to_high(self) -> None:
        r = aggregate_risk([_flag("high"), _flag("high")])
        assert r.level == "high"

    def test_suspect_seller_raises(self) -> None:
        r = aggregate_risk([_flag("low")], seller_suspect=True)
        assert r.level in ("medium", "high")

    def test_clean_is_none(self) -> None:
        r = aggregate_risk([])
        assert r.level == "none"

    def test_minor_flags_low(self) -> None:
        r = aggregate_risk([_flag("low")])
        assert r.level == "low"
