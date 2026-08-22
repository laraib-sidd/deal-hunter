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

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 3
BASE_BACKOFF = 2.0  # seconds


def _tls_context(netskope_ca: str = "/private/etc/netskope/netskope-cert-bundle.pem") -> ssl.SSLContext | bool:
    """An SSL context trusting the corporate CA bundle if present, else True."""
    if os.path.exists(netskope_ca):
        ctx = ssl.create_default_context(cafile=netskope_ca)
        return ctx
    return True


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
        # per-host: when the last request for that host completed (rate limiting)
        self._last_request: dict[str, float] = defaultdict(float)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers=self._headers,
            follow_redirects=follow_redirects,
            verify=_tls_context(netskope_ca or "/private/etc/netskope/netskope-cert-bundle.pem"),
        )

    async def __aenter__(self) -> HttpFetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _throttle(self, host: str, min_interval: float) -> None:
        """Rate-limit requests to a single host (respect 'retry-after'/courtesy delay)."""
        if min_interval <= 0:
            return
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
    ) -> httpx.Response | None:
        """GET with concurrency gate, per-host rate limit, and retry/backoff.

        Returns the response for 2xx (and non-retryable codes like 404), or None after
        exhausting retries. Never raises on transient errors.
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
                        await asyncio.sleep(self._base_backoff * (2 ** attempt))
                        continue
                    return None

                if resp.status_code in retry_on:
                    retry_after = resp.headers.get("retry-after")
                    delay = float(retry_after) if retry_after else self._base_backoff * (2 ** attempt)
                    logger.info("GET %s -> %d, backoff %.1fs", url, resp.status_code, delay)
                    if attempt < self._max_retries:
                        await asyncio.sleep(min(delay, 30))
                        continue
                    return None

                return resp

            return None

    async def fetch_text(self, url: str, **kwargs) -> str | None:
        """Convenience: GET and return response text, or None on failure."""
        resp = await self.get(url, **kwargs)
        return resp.text if resp is not None else None
