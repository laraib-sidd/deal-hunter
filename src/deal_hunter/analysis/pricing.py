"""Depreciation model and fair value calculator for used hardware."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

# Monthly depreciation rates by category (exponential decay).
# Calibrated against TechEnclave Q1 2026 transaction data:
#   GPU  @ 36mo -> ~50% depreciation (RTX 3060: 12-17k vs 29.5k MSRP)
#   GPU  @ 48mo -> ~60% depreciation (RTX 3080: 25-33k vs 62k MSRP)
#   CPU  @ 36mo -> ~45% depreciation
#   RAM  -> holds value well, ~15-20%/year
DEPRECIATION_RATES: dict[str, float] = {
    "gpu": 0.020,
    "cpu": 0.017,
    "laptop": 0.022,
    "ram": 0.010,
    "ssd": 0.013,
    "monitor": 0.008,
    "motherboard": 0.015,
    "psu": 0.010,
}

# Fair value is expressed as a range: [low, high] around the midpoint.
# This spread accounts for condition variance (scratched vs mint).
CONDITION_SPREAD = 0.15  # +/- 15% from midpoint


@dataclass(frozen=True)
class FairValueEstimate:
    """Fair market value range for a used hardware item."""

    midpoint: int  # INR, center of fair range
    low: int  # INR, fair low (rough condition)
    high: int  # INR, fair high (mint condition)
    msrp: int  # INR, original new price
    age_months: int
    depreciation_pct: float  # total depreciation as 0.0-1.0


def calculate_age_months(release_date: str, reference_date: date | None = None) -> int:
    """Calculate age in months from a 'YYYY-MM' release date string."""
    ref = reference_date or date.today()
    parts = release_date.split("-")
    release_year = int(parts[0])
    release_month = int(parts[1]) if len(parts) > 1 else 1
    return max(0, (ref.year - release_year) * 12 + (ref.month - release_month))


def estimate_fair_value(
    msrp_inr: int,
    age_months: int,
    category: str,
) -> FairValueEstimate:
    """Estimate fair used price using exponential depreciation.

    Model: value = msrp * e^(-rate * months)
    The rate varies by category — GPUs depreciate faster than monitors.
    A +/- 15% spread around the midpoint accounts for condition variance.
    """
    rate = DEPRECIATION_RATES.get(category, 0.025)
    depreciation_factor = math.exp(-rate * age_months)

    # Floor at 10% of MSRP — hardware doesn't go to zero
    depreciation_factor = max(depreciation_factor, 0.10)

    midpoint = round(msrp_inr * depreciation_factor)
    spread = round(midpoint * CONDITION_SPREAD)

    return FairValueEstimate(
        midpoint=midpoint,
        low=max(midpoint - spread, round(msrp_inr * 0.08)),
        high=midpoint + spread,
        msrp=msrp_inr,
        age_months=age_months,
        depreciation_pct=round(1.0 - depreciation_factor, 3),
    )


def price_vs_fair_pct(asking_price: float, fair: FairValueEstimate) -> float:
    """How does the asking price compare to fair midpoint?

    Negative = below fair (good for buyer).
    Positive = above fair (overpriced).
    Returns percentage, e.g. -15.0 means 15% below fair.
    """
    if fair.midpoint == 0:
        return 0.0
    return round(((asking_price - fair.midpoint) / fair.midpoint) * 100, 1)
