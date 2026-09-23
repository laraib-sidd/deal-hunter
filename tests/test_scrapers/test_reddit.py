"""Tests for Reddit scraper filtering logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deal_hunter.scrapers.parsing import extract_location, extract_price
from deal_hunter.scrapers.reddit import RedditScraper, _is_hardware_sale_post


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
        assert extract_price("RTX 3060 Rs 15000 Mumbai") == 15000

    def test_rupee_symbol(self) -> None:
        assert extract_price("₹25,000 for the lot") == 25000

    def test_no_price(self) -> None:
        assert extract_price("selling GPU PM for price") is None


class TestLocationExtraction:
    def test_location_label(self) -> None:
        assert extract_location("Location: Hyderabad") == "Hyderabad"

    def test_based_in(self) -> None:
        loc = extract_location("Based in Pune, can ship")
        assert loc is not None
        assert "Pune" in loc

    def test_no_location(self) -> None:
        assert extract_location("selling gpu cheap") is None


class _FakeSubmission:
    def __init__(self, submission_id: str, title: str, body: str = "") -> None:
        self.id = submission_id
        self.title = title
        self.selftext = body
        self.created_utc = 1_700_000_000
        self.permalink = f"/r/IndianGaming/comments/{submission_id}/test/"
        self.author = "seller"


class _FakeSubreddit:
    def __init__(self, submissions: list[_FakeSubmission]) -> None:
        self._submissions = submissions

    def new(self, limit: int):
        del limit
        yield from self._submissions


class TestKnownIdsCursor:
    def test_scrape_stops_at_known_id(self) -> None:
        submissions = [
            _FakeSubmission("aaa111", "Selling RTX 3060 Mumbai", "Rs 15000"),
            _FakeSubmission("bbb222", "Selling RTX 3080 Mumbai", "Rs 25000"),
            _FakeSubmission("ccc333", "Selling RTX 3070 Mumbai", "Rs 20000"),
        ]
        fake_reddit = MagicMock()
        fake_reddit.subreddit.return_value = _FakeSubreddit(submissions)

        scraper = RedditScraper(
            client_id="test-id",
            client_secret="test-secret",
            subreddits=["IndianGaming"],
        )

        with patch("deal_hunter.scrapers.reddit.praw.Reddit", return_value=fake_reddit):
            listings = scraper._scrape_sync(None, 3, {"bbb222"})

        assert len(listings) == 1
        assert listings[0].source_id == "aaa111"
