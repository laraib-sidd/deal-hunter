"""Tests for AI fallback normalizer (Groq)."""

from __future__ import annotations

import json

import pytest

from deal_hunter.analysis.ai_normalizer import ai_normalize

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _groq_response(content: dict) -> dict:
    """Build a Groq/OpenAI-compatible chat completion response."""
    return {"choices": [{"message": {"content": json.dumps(content)}}]}


@pytest.mark.asyncio
async def test_normalizes_unknown_product(httpx_mock) -> None:
    ai_response = {
        "canonical_name": "Crucial T705 4TB PCIe Gen5 NVMe SSD",
        "category": "ssd",
        "brand": "Crucial",
        "generation": "PCIe Gen5",
        "msrp_inr": 52000,
        "release_year": "2024-03",
    }
    httpx_mock.add_response(url=GROQ_URL, json=_groq_response(ai_response))

    result = await ai_normalize("Crucial T705 4TB Gen 5 SSD", api_key="test-key")
    assert result is not None
    assert result.canonical_name == "Crucial T705 4TB PCIe Gen5 NVMe SSD"
    assert result.category == "ssd"
    assert result.brand == "Crucial"
    assert result.msrp_inr == 52000
    assert result.confidence == 0.75


@pytest.mark.asyncio
async def test_no_key_returns_none() -> None:
    result = await ai_normalize("Some product", api_key="")
    assert result is None


@pytest.mark.asyncio
async def test_api_error_returns_none(httpx_mock) -> None:
    httpx_mock.add_response(url=GROQ_URL, status_code=500)
    result = await ai_normalize("Some product", api_key="test-key")
    assert result is None


@pytest.mark.asyncio
async def test_handles_year_only_release(httpx_mock) -> None:
    ai_response = {
        "canonical_name": "WD Red 2TB NAS Drive",
        "category": "storage",
        "brand": "Western Digital",
        "generation": "SATA III",
        "msrp_inr": 6000,
        "release_year": "2022",
    }
    httpx_mock.add_response(url=GROQ_URL, json=_groq_response(ai_response))

    result = await ai_normalize("WD Red 2TB 5400RPM NAS Drive", api_key="test-key")
    assert result is not None
    assert result.release_date == "2022-01"
