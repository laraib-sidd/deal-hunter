"""Tests for the shared HttpFetcher (retry/backoff, fail-closed)."""
from __future__ import annotations

import pytest
import pytest_httpx

from deal_hunter.scrapers.http import FetchResult, HttpFetcher


@pytest.mark.anyio
async def test_returns_body_on_200(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    httpx_mock.add_response(url="https://example.test/a", text="hello")
    async with HttpFetcher(max_retries=2) as client:
        result = await client.get("https://example.test/a")
    assert isinstance(result, FetchResult)
    assert result.status == "success"
    assert result.response is not None
    assert result.response.status_code == 200
    assert result.response.text == "hello"


@pytest.mark.anyio
async def test_returns_not_found_on_404(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    httpx_mock.add_response(url="https://example.test/missing", status_code=404, json={"error": "gone"})
    async with HttpFetcher(max_retries=1) as client:
        result = await client.get("https://example.test/missing")
    assert result.status == "not_found"
    assert result.response is not None
    assert result.response.status_code == 404


@pytest.mark.anyio
async def test_retries_then_succeeds_on_429(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    httpx_mock.add_response(url="https://example.test/r", status_code=429)
    httpx_mock.add_response(url="https://example.test/r", status_code=429)
    httpx_mock.add_response(url="https://example.test/r", status_code=200, text="ok")

    async with HttpFetcher(max_retries=3, base_backoff=0.01) as client:
        result = await client.get("https://example.test/r")

    assert result.status == "success"
    assert result.response is not None
    assert result.response.status_code == 200
    assert len(httpx_mock.get_requests()) == 3


@pytest.mark.anyio
async def test_honors_retry_after_delta_seconds(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://example.test/retry",
        status_code=429,
        headers={"retry-after": "0"},
    )
    httpx_mock.add_response(url="https://example.test/retry", status_code=200, text="ok")

    async with HttpFetcher(max_retries=2, base_backoff=999) as client:
        result = await client.get("https://example.test/retry")

    assert result.status == "success"
    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.anyio
async def test_returns_exhausted_when_exhausting_retries(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    httpx_mock.add_response(url="https://example.test/f", status_code=503)
    httpx_mock.add_response(url="https://example.test/f", status_code=503)
    httpx_mock.add_response(url="https://example.test/f", status_code=503)

    async with HttpFetcher(max_retries=2, base_backoff=0.01) as client:
        result = await client.get("https://example.test/f")

    assert result.status == "exhausted"
    assert result.response is None

@pytest.mark.anyio
async def test_fetch_result_drop_in_attributes_without_attribute_error(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    """Legacy callers can read .status_code and .json() on all outcomes."""
    httpx_mock.add_response(
        url="https://example.test/ok",
        status_code=200,
        json={"topics": [1]},
    )
    httpx_mock.add_response(url="https://example.test/missing", status_code=404, json={"error": "gone"})
    httpx_mock.add_response(url="https://example.test/fail", status_code=503)
    httpx_mock.add_response(url="https://example.test/fail", status_code=503)

    async with HttpFetcher(max_retries=1, base_backoff=0.01) as client:
        ok = await client.get("https://example.test/ok")
        missing = await client.get("https://example.test/missing")
        exhausted = await client.get("https://example.test/fail")

    assert ok.status_code == 200
    assert ok.json() == {"topics": [1]}
    assert ok.text
    assert ok.headers

    assert missing.status_code == 404
    assert missing.json() == {"error": "gone"}

    assert exhausted.status_code == 0
    assert exhausted.json() == {}
    assert exhausted.text == ""
    assert exhausted.headers == {}

