"""Shared HTTP fetching with timeout, concurrency, rate-limit and retry.

Dependency-Inversion: scrapers depend on this interface instead of raw `httpx`, so
timeout/backoff/concurrency behaviour is configured in one place. This is what stops the
TechEnclave-style hang (no global deadline) from silently blocking a run.
"""
from __future__ import annotations

import asyncio
import logging
import os
import ssl
import time
from collections import defaultdict
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 3
BASE_BACKOFF = 2.0  # seconds
MAX_BACKOFF = 30.0

FetchStatus = Literal["success", "not_found", "exhausted"]

_fetch_exhausted: ContextVar[bool] = ContextVar("fetch_exhausted", default=False)


def reset_fetch_exhausted() -> None:
    """Clear the per-scrape exhaustion flag before a scraper run."""
    _fetch_exhausted.set(False)


def fetch_was_exhausted() -> bool:
    """Whether any ``HttpFetcher.get()`` in this context returned exhausted."""
    return _fetch_exhausted.get()


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Outcome of a GET — drop-in for legacy ``resp.status_code`` / ``resp.json()``."""

    status: FetchStatus
    response: httpx.Response | None = None

    @property
    def status_code(self) -> int:
        if self.response is not None:
            return self.response.status_code
        return 0

    @property
    def text(self) -> str:
        if self.response is not None:
            return self.response.text
        return ""

    @property
    def headers(self) -> Mapping[str, str]:
        if self.response is not None:
            return self.response.headers
        return {}

    def json(self) -> Any:
        if self.response is not None:
            return self.response.json()
        return {}


def _tls_context(netskope_ca: str = "/private/etc/netskope/netskope-cert-bundle.pem") -> ssl.SSLContext | bool:
    """An SSL context trusting the corporate CA bundle if present, else True."""
    if os.path.exists(netskope_ca):
        ctx = ssl.create_default_context(cafile=netskope_ca)
        return ctx
    return True


def _parse_retry_after(value: str | None, attempt: int, base_backoff: float) -> float:
    """Honor Retry-After only when it is delta-seconds; else exponential backoff."""
    if not value:
        return base_backoff * (2**attempt)
    try:
        return float(value)
    except ValueError:
        return base_backoff * (2**attempt)


class HttpFetcher:
    """Async HTTP client wrapper: single shared connection pool + controls.

    Use as a context manager. Requests are throttled per-host and retried with
    exponential backoff on transient errors / 429 / 5xx.
    """

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        base_backoff: float = BASE_BACKOFF,
        max_concurrent: int = 5,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
        netskope_ca: str | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._headers = headers or {"User-Agent": "DealHunter/0.1 (personal research tool)"}
        self._sem = asyncio.Semaphore(max_concurrent)
        self._last_request: dict[str, float] = defaultdict(float)
        self._host_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        ca_path = netskope_ca or "/private/etc/netskope/netskope-cert-bundle.pem"
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            transport=httpx.AsyncHTTPTransport(retries=1),
            headers=self._headers,
            follow_redirects=follow_redirects,
            verify=_tls_context(ca_path),
        )

    async def __aenter__(self) -> HttpFetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _throttle(self, host: str, min_interval: float) -> None:
        """Rate-limit requests to a single host (race-free under concurrent callers)."""
        if min_interval <= 0:
            return
        lock = self._host_locks[host]
        async with lock:
            wait = self._last_request[host] + min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request[host] = time.monotonic()

    async def get(
        self,
        url: str,
        *,
        params: dict | None = None,
        host_min_interval: float = 0.0,
        retry_on: tuple[int, ...] = (429, 500, 502, 503, 504),
    ) -> FetchResult:
        """GET with concurrency gate, per-host rate limit, and retry/backoff.

        Returns success (2xx), not_found (404), or exhausted after retries.
        Never raises on transient errors.
        """
        host = httpx.URL(url).host
        async with self._sem:
            for attempt in range(self._max_retries + 1):
                await self._throttle(host, host_min_interval)
                try:
                    resp = await self._client.get(url, params=params)
                except (httpx.HTTPError, httpx.TimeoutException) as exc:
                    logger.debug("GET %s error (attempt %d): %s", url, attempt + 1, exc)
                    if attempt < self._max_retries:
                        await asyncio.sleep(min(self._base_backoff * (2**attempt), MAX_BACKOFF))
                        continue
                    _fetch_exhausted.set(True)
                    return FetchResult(status="exhausted")

                if resp.status_code == 404:
                    return FetchResult(status="not_found", response=resp)

                if resp.status_code in retry_on:
                    delay = _parse_retry_after(
                        resp.headers.get("retry-after"), attempt, self._base_backoff
                    )
                    logger.info("GET %s -> %d, backoff %.1fs", url, resp.status_code, delay)
                    if attempt < self._max_retries:
                        await asyncio.sleep(min(delay, MAX_BACKOFF))
                        continue
                    _fetch_exhausted.set(True)
                    return FetchResult(status="exhausted")

                return FetchResult(status="success", response=resp)

            _fetch_exhausted.set(True)
            return FetchResult(status="exhausted")

    async def fetch_text(self, url: str, **kwargs) -> str | None:
        """Convenience: GET and return response text, or None on failure."""
        result = await self.get(url, **kwargs)
        if result.status == "success" and result.response is not None:
            return result.response.text
        return None
