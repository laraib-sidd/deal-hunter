"""Tests for the deal scorer end-to-end."""

from __future__ import annotations

from deal_hunter.analysis.scorer import analyze_deal, extract_price


class TestPriceExtraction:
    def test_rs_prefix(self) -> None:
        assert extract_price("Rs. 16,500") == 16500

    def test_inr_prefix(self) -> None:
        assert extract_price("INR 25000") == 25000

    def test_rupee_symbol(self) -> None:
        assert extract_price("₹32,000") == 32000

    def test_price_in_sentence(self) -> None:
        assert extract_price("Selling RTX 3060 for Rs 15000 in Mumbai") == 15000

    def test_asking_price_label(self) -> None:
        assert extract_price("Asking price: 18,500") == 18500

    def test_no_price_returns_none(self) -> None:
        assert extract_price("Selling my old GPU") is None

    def test_ignores_tiny_numbers(self) -> None:
        assert extract_price("Rs 50") is None


class TestDealAnalysis:
    def test_good_deal_rtx_3060(self) -> None:
        result = analyze_deal("RTX 3060 12GB", asking_price=12000)
        assert result is not None
        assert result.canonical_name == "NVIDIA GeForce RTX 3060"
        assert result.category == "gpu"
        assert result.asking_price == 12000

    def test_overpriced_listing(self) -> None:
        result = analyze_deal("RTX 3060", asking_price=28000)
        assert result is not None
        assert result.price_vs_fair_pct > 0
        assert result.deal_score <= 5

    def test_price_extracted_from_text(self) -> None:
        result = analyze_deal("RTX 3070 ₹18,000 in Mumbai")
        assert result is not None
        assert result.asking_price == 18000

    def test_unknown_hardware_returns_none(self) -> None:
        result = analyze_deal("vintage toaster", asking_price=500)
        assert result is None

    def test_mining_flag_on_rtx_3060_ti(self) -> None:
        result = analyze_deal(
            "RTX 3060 Ti",
            asking_price=14000,
            description="Used for mining, 24/7 operation",
        )
        assert result is not None
        flag_types = [f.flag_type for f in result.red_flags]
        assert "mining_popular_model" in flag_types
        assert "mining_keywords" in flag_types
