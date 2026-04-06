"""Tests for hardware name normalization."""

from __future__ import annotations

import pytest

from deal_hunter.analysis.normalizer import HardwareNormalizer


@pytest.fixture
def nrm() -> HardwareNormalizer:
    return HardwareNormalizer()


class TestRegexMatching:
    def test_rtx_3060_various_forms(self, nrm: HardwareNormalizer) -> None:
        for text in ["RTX 3060", "rtx3060", "nvidia 3060", "geforce rtx 3060 12gb"]:
            match = nrm.normalize(text)
            assert match is not None, f"Failed to match: {text}"
            assert match.hardware_id == "nvidia-rtx-3060"
            assert match.confidence >= 0.90

    def test_rtx_3060_ti_not_confused_with_3060(self, nrm: HardwareNormalizer) -> None:
        match = nrm.normalize("RTX 3060 Ti")
        assert match is not None
        assert match.hardware_id == "nvidia-rtx-3060-ti"

    def test_rtx_4070_ti_super(self, nrm: HardwareNormalizer) -> None:
        match = nrm.normalize("RTX 4070 Ti Super")
        assert match is not None
        assert match.hardware_id == "nvidia-rtx-4070-ti-super"

    def test_amd_rx_580(self, nrm: HardwareNormalizer) -> None:
        match = nrm.normalize("RX 580 8GB")
        assert match is not None
        assert match.hardware_id == "amd-rx-580"
        assert match.category == "gpu"

    def test_ryzen_5600x(self, nrm: HardwareNormalizer) -> None:
        match = nrm.normalize("Ryzen 5 5600X")
        assert match is not None
        assert match.hardware_id == "amd-ryzen-5-5600x"
        assert match.category == "cpu"

    def test_intel_i5_12400f(self, nrm: HardwareNormalizer) -> None:
        match = nrm.normalize("i5 12400f")
        assert match is not None
        assert match.hardware_id == "intel-i5-12400f"

    def test_unknown_returns_none(self, nrm: HardwareNormalizer) -> None:
        match = nrm.normalize("random household item toaster")
        assert match is None


class TestFuzzyMatching:
    def test_fuzzy_ddr4_16gb(self, nrm: HardwareNormalizer) -> None:
        match = nrm.normalize("ddr4 16gb ram 3200mhz")
        assert match is not None
        assert match.category == "ram"
        assert match.confidence <= 0.90  # fuzzy cap

    def test_fuzzy_nvme_ssd(self, nrm: HardwareNormalizer) -> None:
        match = nrm.normalize("1tb nvme ssd")
        assert match is not None
        assert match.category == "ssd"


class TestMetadata:
    def test_mining_popular_list_exists(self, nrm: HardwareNormalizer) -> None:
        assert len(nrm.mining_popular_ids) > 0
        assert "nvidia-rtx-3060-ti" in nrm.mining_popular_ids

    def test_city_tiers_exist(self, nrm: HardwareNormalizer) -> None:
        tiers = nrm.city_tiers
        assert "tier_1" in tiers
        assert "mumbai" in tiers["tier_1"]
