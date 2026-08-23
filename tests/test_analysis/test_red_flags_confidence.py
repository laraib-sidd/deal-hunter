"""Test the SCAM_RISK over-fire fix: confidence gates suspicious-price severity."""
from __future__ import annotations

from deal_hunter.analysis.normalizer import HardwareMatch
from deal_hunter.analysis.pricing import FairValueEstimate
from deal_hunter.analysis.red_flags import detect_red_flags


def _make_hw(confidence: float) -> HardwareMatch:
    return HardwareMatch(
        hardware_id="test-rtx-3080",
        canonical_name="NVIDIA GeForce RTX 3080",
        category="gpu",
        brand="NVIDIA",
        generation="Ampere",
        msrp_inr=62000,
        release_date="2020-09",
        confidence=confidence,
    )


def _fair(midpoint: int = 25000) -> FairValueEstimate:
    return FairValueEstimate(midpoint=midpoint, low=20000, high=30000, msrp=62000, age_months=48, depreciation_pct=0.6)


class TestSuspiciousPriceConfidence:
    def test_low_confidence_cheap_not_scam(self) -> None:
        # price well below fair but HW identity confidence is low -> NOT critical scam
        flags = detect_red_flags(
            hw=_make_hw(confidence=0.3),
            fair=_fair(25000),
            asking_price=12000,  # well below fair.low*0.8
            confidence=0.3,
        )
        critical = [f for f in flags if f.severity == "critical"]
        assert not critical  # must not over-fire SCAM_RISK on low confidence

    def test_high_confidence_cheap_is_critical(self) -> None:
        # Confident identity + price under 50% of fair -> legitimate scam signal
        flags = detect_red_flags(
            hw=_make_hw(confidence=0.95),
            fair=_fair(25000),
            asking_price=8000,  # < fair.low*0.5
            confidence=0.95,
        )
        assert any(f.severity == "critical" and f.flag_type == "suspicious_price" for f in flags)

    def test_mid_price_low_conf_not_scam(self) -> None:
        # 0.6x fair low with low confidence -> below_market medium, not critical
        flags = detect_red_flags(
            hw=_make_hw(confidence=0.2),
            fair=_fair(25000),
            asking_price=14000,  # ~0.7x low
            confidence=0.2,
        )
        assert not any(f.severity == "critical" for f in flags)
