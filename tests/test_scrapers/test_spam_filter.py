"""Tests for UPI/trade-spam exclusion in Reddit filtering."""
from __future__ import annotations

from deal_hunter.scrapers.reddit import _is_deal_post, _is_hardware_sale_post


class TestSpamExclusion:
    def test_hardware_deal_still_passes(self) -> None:
        assert _is_hardware_sale_post("Selling RTX 3080 in Mumbai", "Rs 25000")

    def test_upi_spam_rejected_as_hardware(self) -> None:
        # UPI trade posts are not hardware listings
        assert not _is_hardware_sale_post("[H] 500 upi [W] Amazon gc", "")
        assert not _is_hardware_sale_post("selling vouchers", "95% upi amazon gc")

    def test_upi_spam_rejected_as_deal(self) -> None:
        assert not _is_deal_post("[H] 1000 upi [W] flipkart gc", "")
        assert not _is_deal_post("gift cards", "80% upi exchange")

    def test_voucher_without_hardware_rejected_as_deal(self) -> None:
        assert not _is_deal_post("Flat 50% off on Nike shoes", "use code LOOT50")

    def test_coupon_with_hardware_rejected_as_deal(self) -> None:
        assert not _is_deal_post("20% off RTX 3060", "use promo code SAVE20")

    def test_hardware_sale_passes_in_deal_sub(self) -> None:
        assert _is_deal_post("Selling RTX 3080 in Mumbai", "Rs 25000")

    def test_hardware_with_payment_context_allowed(self) -> None:
        # A legit GPU listing that mentions price still qualifies
        assert _is_hardware_sale_post("WTB RTX 3060 under 20k", "will pay via upi")
