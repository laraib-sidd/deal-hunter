"""Shared Groq API client with rate limit handling."""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RETRIES = 3
BASE_DELAY = 2.0  # seconds


async def groq_chat(
    api_key: str,
    messages: list[dict],
    model: str = "meta-llama/llama-4-scout-17b-16e-instruct",
    max_tokens: int = 300,
    temperature: float = 0.1,
    json_mode: bool = True,
) -> dict | None:
    """Send a chat completion to Groq with automatic retry on rate limits.

    Returns the parsed response dict or None on failure.
    """
    payload: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(GROQ_API_URL, headers=headers, json=payload)

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 429:
                # Rate limited — extract retry-after or use exponential backoff
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if retry_after else BASE_DELAY * (2 ** attempt)
                logger.info("Groq rate limited, waiting %.1fs (attempt %d/%d)", delay, attempt + 1, MAX_RETRIES)
                await asyncio.sleep(delay)
                continue

            logger.debug("Groq returned %d: %s", resp.status_code, resp.text[:100])
            return None

        except httpx.HTTPError as exc:
            logger.debug("Groq request error: %s", exc)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(BASE_DELAY)
                continue
            return None

    logger.warning("Groq rate limit exceeded after %d retries", MAX_RETRIES)
    return None


def extract_content(response: dict) -> str:
    """Extract the text content from a Groq chat completion response."""
    text = response["choices"][0]["message"]["content"]
    # Handle markdown code blocks
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()
