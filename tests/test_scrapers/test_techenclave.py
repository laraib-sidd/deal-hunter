"""Tests for TechEnclave scraper parsing logic."""

from __future__ import annotations

from deal_hunter.scrapers.techenclave import _extract_location, _extract_price, _strip_html


class TestPriceExtraction:
    def test_rs_prefix(self) -> None:
        assert _extract_price("Asking Rs. 25,000 for the GPU") == 25000

    def test_rupee_symbol(self) -> None:
        assert _extract_price("<p>Price: ₹18,500</p>") == 18500

    def test_inr_prefix(self) -> None:
        assert _extract_price("INR 32000 final") == 32000

    def test_price_in_html(self) -> None:
        html = "<p><strong>Price:</strong> Rs 15,000</p>"
        assert _extract_price(html) == 15000

    def test_no_price(self) -> None:
        assert _extract_price("<p>selling my old GPU</p>") is None


class TestLocationExtraction:
    def test_location_label(self) -> None:
        html = "<p>Location: Mumbai</p>"
        assert _extract_location(html) == "Mumbai"

    def test_city_label(self) -> None:
        html = "<p>City: Bangalore</p>"
        assert _extract_location(html) == "Bangalore"

    def test_no_location(self) -> None:
        assert _extract_location("<p>Selling GPU</p>") is None


class TestStripHtml:
    def test_basic_strip(self) -> None:
        result = _strip_html("<p>Hello <strong>world</strong></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result
