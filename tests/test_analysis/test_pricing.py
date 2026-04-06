"""Tests for depreciation model and fair value calculator."""

from __future__ import annotations

from datetime import date

from deal_hunter.analysis.pricing import (
    calculate_age_months,
    estimate_fair_value,
    price_vs_fair_pct,
)


class TestAgeCalculation:
    def test_recent_product(self) -> None:
        age = calculate_age_months("2025-01", reference_date=date(2026, 4, 1))
        assert age == 15

    def test_old_product(self) -> None:
        age = calculate_age_months("2020-09", reference_date=date(2026, 4, 1))
        assert age == 67

    def test_year_only(self) -> None:
        age = calculate_age_months("2024", reference_date=date(2026, 4, 1))
        assert age == 27  # 2024-01 to 2026-04

    def test_future_returns_zero(self) -> None:
        age = calculate_age_months("2027-01", reference_date=date(2026, 4, 1))
        assert age == 0


class TestFairValue:
    def test_new_gpu_minimal_depreciation(self) -> None:
        fair = estimate_fair_value(msrp_inr=30000, age_months=3, category="gpu")
        # 3 months at 3.5%/month -> ~90% of MSRP
        assert 25000 < fair.midpoint < 30000

    def test_old_gpu_heavy_depreciation(self) -> None:
        fair = estimate_fair_value(msrp_inr=60000, age_months=48, category="gpu")
        # 48 months at 2.0%/month -> ~38% of MSRP = ~23k
        assert fair.midpoint < 30000
        assert fair.depreciation_pct > 0.5

    def test_floor_at_10_percent(self) -> None:
        fair = estimate_fair_value(msrp_inr=100000, age_months=200, category="gpu")
        # Should hit the 10% floor
        assert fair.midpoint >= 10000

    def test_ram_depreciates_slower(self) -> None:
        gpu_fair = estimate_fair_value(msrp_inr=30000, age_months=24, category="gpu")
        ram_fair = estimate_fair_value(msrp_inr=30000, age_months=24, category="ram")
        assert ram_fair.midpoint > gpu_fair.midpoint

    def test_spread_around_midpoint(self) -> None:
        fair = estimate_fair_value(msrp_inr=50000, age_months=12, category="gpu")
        assert fair.low < fair.midpoint < fair.high


class TestPriceComparison:
    def test_below_fair_is_negative(self) -> None:
        fair = estimate_fair_value(msrp_inr=30000, age_months=12, category="gpu")
        pct = price_vs_fair_pct(fair.midpoint * 0.8, fair)
        assert pct < 0

    def test_above_fair_is_positive(self) -> None:
        fair = estimate_fair_value(msrp_inr=30000, age_months=12, category="gpu")
        pct = price_vs_fair_pct(fair.midpoint * 1.2, fair)
        assert pct > 0

    def test_at_fair_is_zero(self) -> None:
        fair = estimate_fair_value(msrp_inr=30000, age_months=12, category="gpu")
        pct = price_vs_fair_pct(fair.midpoint, fair)
        assert pct == 0.0
