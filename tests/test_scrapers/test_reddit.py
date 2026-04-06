"""Tests for Reddit scraper filtering logic."""

from __future__ import annotations

from deal_hunter.scrapers.reddit import _extract_location, _extract_price, _is_hardware_sale_post


class TestPostFiltering:
    def test_selling_gpu(self) -> None:
        assert _is_hardware_sale_post("Selling RTX 3060 in Mumbai", "")

    def test_wts_format(self) -> None:
        assert _is_hardware_sale_post("[WTS] Ryzen 5 5600X", "barely used")

    def test_hwswap_format(self) -> None:
        assert _is_hardware_sale_post("[H] RTX 4070 [W] PayPal", "")

    def test_wtb_format(self) -> None:
        assert _is_hardware_sale_post("WTB: RTX 3080 under 30k", "")

    def test_general_discussion_rejected(self) -> None:
        assert not _is_hardware_sale_post("Which GPU should I buy?", "I'm confused between 3060 and 4060")

    def test_no_hardware_rejected(self) -> None:
        assert not _is_hardware_sale_post("Selling my old chair", "good condition")

    def test_laptop_sale(self) -> None:
        assert _is_hardware_sale_post("FS: Dell Laptop i7", "selling my laptop")


class TestPriceExtraction:
    def test_rs_in_title(self) -> None:
        assert _extract_price("RTX 3060 Rs 15000 Mumbai") == 15000

    def test_rupee_symbol(self) -> None:
        assert _extract_price("₹25,000 for the lot") == 25000

    def test_no_price(self) -> None:
        assert _extract_price("selling GPU PM for price") is None


class TestLocationExtraction:
    def test_location_label(self) -> None:
        assert _extract_location("Location: Hyderabad") == "Hyderabad"

    def test_based_in(self) -> None:
        loc = _extract_location("Based in Pune, can ship")
        assert loc is not None
        assert "Pune" in loc

    def test_no_location(self) -> None:
        assert _extract_location("selling gpu cheap") is None
