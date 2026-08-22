"""Tests for the shared HttpFetcher (retry/backoff, fail-closed)."""
from __future__ import annotations

import pytest
import pytest_httpx

from deal_hunter.scrapers.http import HttpFetcher


@pytest.mark.anyio
async def test_returns_body_on_200(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    httpx_mock.add_response(url="https://example.test/a", text="hello")
    async with HttpFetcher(max_retries=2) as client:
        resp = await client.get("https://example.test/a")
    assert resp is not None
    assert resp.status_code == 200
    assert resp.text == "hello"


@pytest.mark.anyio
async def test_retries_then_succeeds_on_429(httpx_mock: pytest_httpx.HTTPXMock) -> None:
    # First two calls -> 429, third -> 200
    httpx_mock.add_response(url="https://example.test/r", status_code=429)
    httpx_mock.add_response(url="https://example.test/r", status_code=429)
    httpx_mock.add_response(url="https://example.test/r", status_code=200, text="ok")

    async with HttpFetcher(max_retries=3, base_backoff=0.01) as client:
        resp = await client.get("https://example.test/r")

    assert resp is not None
    assert resp.status_code == 200
    # 3 requests total: 2 failures + 1 success
    assert len(httpx_mock.get_requests()) == 3


@pytest.mark.anyio
async def test_returns_none_when_exhausting_retries(
    httpx_mock: pytest_httpx.HTTPXMock,
) -> None:
    httpx_mock.add_response(url="https://example.test/f", status_code=503)
    httpx_mock.add_response(url="https://example.test/f", status_code=503)
    httpx_mock.add_response(url="https://example.test/f", status_code=503)

    async with HttpFetcher(max_retries=2, base_backoff=0.01) as client:
        resp = await client.get("https://example.test/f")

    assert resp is None  # never succeeded, exhausted retries
