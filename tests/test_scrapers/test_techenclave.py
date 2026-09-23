"""Tests for TechEnclave scraper parsing and incremental scrape logic."""

from __future__ import annotations

import re

import pytest
import pytest_httpx

from deal_hunter.scrapers.parsing import extract_location, extract_price, strip_html
from deal_hunter.scrapers.techenclave import TechEnclaveScraper

pytestmark = [
    pytest.mark.httpx_mock(
        assert_all_responses_were_requested=False,
        assert_all_requests_were_expected=False,
    )
]


def _empty_category_page() -> dict:
    return {"topic_list": {"topics": []}}


def _topic_detail(topic_id: int, title: str, body: str, username: str = "seller1") -> dict:
    return {
        "title": title,
        "slug": f"topic-{topic_id}",
        "created_at": "2024-01-01T00:00:00.000Z",
        "post_stream": {
            "posts": [
                {
                    "username": username,
                    "cooked": f"<p>{body}</p>",
                }
            ]
        },
    }


def _mock_categories(
    httpx_mock: pytest_httpx.HTTPXMock,
    overrides: dict[tuple[int, str], dict] | None = None,
) -> None:
    """Register one list response per marketplace category (first match wins)."""
    overrides = overrides or {}
    for cat_id, cat_slug in (
        (64, "classifieds"),
        (61, "flash-deals"),
        (19, "garage-sale"),
        (18, "looking-to-buy"),
    ):
        payload = overrides.get((cat_id, cat_slug), _empty_category_page())
        httpx_mock.add_response(
            url=re.compile(
                rf"https://techenclave\.com/c/trading-post/{cat_slug}/{cat_id}\.json"
            ),
            json=payload,
        )


class TestPriceExtraction:
    def test_rs_prefix(self) -> None:
        assert extract_price("Asking Rs. 25,000 for the GPU") == 25000

    def test_rupee_symbol(self) -> None:
        assert extract_price("<p>Price: ₹18,500</p>") == 18500

    def test_inr_prefix(self) -> None:
        assert extract_price("INR 32000 final") == 32000

    def test_price_in_html(self) -> None:
        html = "<p><strong>Price:</strong> Rs 15,000</p>"
        assert extract_price(html) == 15000

    def test_no_price(self) -> None:
        assert extract_price("<p>selling my old GPU</p>") is None


class TestLocationExtraction:
    def test_location_label(self) -> None:
        html = "<p>Location: Mumbai</p>"
        assert extract_location(html) == "Mumbai"

    def test_city_label(self) -> None:
        html = "<p>City: Bangalore</p>"
        assert extract_location(html) == "Bangalore"

    def test_no_location(self) -> None:
        assert extract_location("<p>Selling GPU</p>") is None


class TestStripHtml:
    def test_basic_strip(self) -> None:
        result = strip_html("<p>Hello <strong>world</strong></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result


@pytest.mark.anyio
async def test_known_topic_does_not_trigger_detail_fetch(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """Incremental mode must not call /t/{id}.json for ids already in known_ids."""
    known_id = 12345
    new_id = 99999

    _mock_categories(
        httpx_mock,
        {
            (64, "classifieds"): {
                "topic_list": {
                    "topics": [
                        {"id": new_id, "title": "RTX 3060 for sale"},
                        {"id": known_id, "title": "Already ingested"},
                    ]
                }
            }
        },
    )

    httpx_mock.add_response(
        url=f"https://techenclave.com/t/{new_id}.json",
        json=_topic_detail(new_id, "RTX 3060 for sale", "Rs 15000 Mumbai"),
    )

    scraper = TechEnclaveScraper()
    listings = await scraper.scrape(max_pages=1, known_ids={str(known_id)})

    requested = [str(req.url) for req in httpx_mock.get_requests()]
    assert not any(f"/t/{known_id}.json" in url for url in requested)
    assert any(f"/t/{new_id}.json" in url for url in requested)
    assert len(listings) == 1
    assert listings[0].source_id == str(new_id)
    assert listings[0].category == "sell"


@pytest.mark.anyio
async def test_known_id_in_middle_stops_older_detail_fetches(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """Known watermark in the middle of a page must not detail-fetch topics after it."""
    known_id = 500
    newer_id = 600
    older_id = 400

    _mock_categories(
        httpx_mock,
        {
            (64, "classifieds"): {
                "topic_list": {
                    "topics": [
                        {"id": newer_id, "title": "New listing"},
                        {"id": known_id, "title": "Already ingested"},
                        {"id": older_id, "title": "Older on same page"},
                    ]
                }
            }
        },
    )

    httpx_mock.add_response(
        url=f"https://techenclave.com/t/{newer_id}.json",
        json=_topic_detail(newer_id, "New listing", "Rs 15000 Mumbai"),
    )

    scraper = TechEnclaveScraper()
    listings = await scraper.scrape(max_pages=1, known_ids={str(known_id)})

    requested = [str(req.url) for req in httpx_mock.get_requests()]
    assert any(f"/t/{newer_id}.json" in url for url in requested)
    assert not any(f"/t/{known_id}.json" in url for url in requested)
    assert not any(f"/t/{older_id}.json" in url for url in requested)
    assert len(listings) == 1
    assert listings[0].source_id == str(newer_id)


@pytest.mark.anyio
async def test_bumped_watermark_topic_gets_detail_fetch(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """Watermark topic with bumped_at after created_at is re-fetched once."""
    known_id = 500
    newer_id = 600

    _mock_categories(
        httpx_mock,
        {
            (64, "classifieds"): {
                "topic_list": {
                    "topics": [
                        {"id": newer_id, "title": "New listing"},
                        {
                            "id": known_id,
                            "title": "Bumped watermark",
                            "created_at": "2024-01-01T00:00:00.000Z",
                            "bumped_at": "2024-01-02T00:00:00.000Z",
                        },
                    ]
                }
            }
        },
    )

    httpx_mock.add_response(
        url=f"https://techenclave.com/t/{newer_id}.json",
        json=_topic_detail(newer_id, "New listing", "Rs 15000 Mumbai"),
    )
    httpx_mock.add_response(
        url=f"https://techenclave.com/t/{known_id}.json",
        json=_topic_detail(known_id, "Bumped watermark", "Updated price Rs 12000"),
    )

    scraper = TechEnclaveScraper()
    listings = await scraper.scrape(max_pages=1, known_ids={str(known_id)})

    requested = [str(req.url) for req in httpx_mock.get_requests()]
    assert any(f"/t/{newer_id}.json" in url for url in requested)
    assert any(f"/t/{known_id}.json" in url for url in requested)
    assert len(listings) == 2
    assert {listing.source_id for listing in listings} == {str(newer_id), str(known_id)}


@pytest.mark.anyio
async def test_wtb_category_gets_wtb_intent(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    topic_id = 55555
    _mock_categories(
        httpx_mock,
        {
            (18, "looking-to-buy"): {
                "topic_list": {"topics": [{"id": topic_id, "title": "Want RTX 3080"}]}
            }
        },
    )
    httpx_mock.add_response(
        url=f"https://techenclave.com/t/{topic_id}.json",
        json=_topic_detail(topic_id, "Want RTX 3080", "Budget 30k"),
    )

    scraper = TechEnclaveScraper()
    listings = await scraper.scrape(max_pages=1)

    assert len(listings) == 1
    assert listings[0].category == "wtb"
    assert listings[0].seller_name == "seller1"


@pytest.mark.anyio
async def test_coupon_post_classified_as_other(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    topic_id = 44444
    _mock_categories(
        httpx_mock,
        {
            (64, "classifieds"): {
                "topic_list": {"topics": [{"id": topic_id, "title": "MMT flight coupon"}]}
            }
        },
    )
    httpx_mock.add_response(
        url=f"https://techenclave.com/t/{topic_id}.json",
        json=_topic_detail(topic_id, "MMT flight coupon", "Use promo code for travel booking"),
    )

    scraper = TechEnclaveScraper()
    listings = await scraper.scrape(max_pages=1)

    assert len(listings) == 1
    assert listings[0].category == "other"


@pytest.mark.anyio
async def test_search_mode_pages_and_dedupes(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    httpx_mock.add_response(
        url=re.compile(r"https://techenclave\.com/search\.json"),
        json={"topics": [{"id": 100, "title": "GPU page 0"}]},
        is_reusable=False,
    )
    httpx_mock.add_response(
        url=re.compile(r"https://techenclave\.com/search\.json"),
        json={
            "topics": [
                {"id": 100, "title": "GPU page 0 dup"},
                {"id": 101, "title": "Page 1 only"},
            ]
        },
    )
    for topic_id, title in ((100, "GPU page 0"), (101, "Page 1 only")):
        httpx_mock.add_response(
            url=f"https://techenclave.com/t/{topic_id}.json",
            json=_topic_detail(topic_id, title, "Rs 10000"),
        )

    scraper = TechEnclaveScraper()
    listings = await scraper.scrape(keywords=["gpu"], max_pages=2)

    search_requests = [
        str(req.url)
        for req in httpx_mock.get_requests()
        if "search.json" in str(req.url)
    ]
    assert len(search_requests) == 2
    assert len(listings) == 2
    assert {listing.source_id for listing in listings} == {"100", "101"}


@pytest.mark.anyio
async def test_list_fetch_exhausted_sets_flag(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    for _ in range(20):
        httpx_mock.add_response(
            url=re.compile(r"https://techenclave\.com/c/trading-post/"),
            status_code=503,
        )

    scraper = TechEnclaveScraper()
    await scraper.scrape(max_pages=1)

    assert scraper.list_fetch_exhausted is True
