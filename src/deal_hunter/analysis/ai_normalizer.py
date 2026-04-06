"""AI fallback normalizer — uses Groq (free tier) when regex+fuzzy fails."""

from __future__ import annotations

import json
import logging

import httpx

from deal_hunter.analysis.normalizer import HardwareMatch

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

PROMPT = """Identify this product from a second-hand listing in India.

Listing title: "{title}"
Description: "{description}"

Return a JSON object with these fields:
- canonical_name: full product name (e.g. "Crucial T700 4TB PCIe Gen5 NVMe SSD")
- category: one of gpu, cpu, ram, ssd, monitor, motherboard, psu, laptop, headphone, keyboard, mouse, case, networking, storage, peripheral, other
- brand: brand name
- generation: tech generation or series (e.g. "PCIe Gen5", "Zen 4", "Wi-Fi 6E")
- msrp_inr: estimated NEW retail price in India in INR (integer)
- release_year: YYYY or YYYY-MM if known

Use current Indian retail prices (Amazon.in/Flipkart). Be accurate with MSRP."""


async def ai_normalize(
    title: str,
    description: str = "",
    api_key: str = "",
    model: str = DEFAULT_MODEL,
) -> HardwareMatch | None:
    """Use Groq to identify unknown hardware. Returns HardwareMatch or None."""
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": PROMPT.format(
                        title=title[:200],
                        description=description[:500],
                    )}],
                    "max_tokens": 300,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )

        if resp.status_code != 200:
            logger.debug("AI normalize failed: %d %s", resp.status_code, resp.text[:100])
            return None

        data = resp.json()
        text = data["choices"][0]["message"]["content"]

        # Groq JSON mode guarantees valid JSON, but handle code blocks just in case
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        result = json.loads(text)

        release = result.get("release_year") or "2023"
        release = str(release).strip()
        if release.lower() in ("none", "null", "unknown", ""):
            release = "2023"
        if len(release) == 4:
            release = f"{release}-01"

        return HardwareMatch(
            hardware_id=f"ai-{result.get('category', 'other')}-{hash(title) & 0xFFFF:04x}",
            canonical_name=result.get("canonical_name") or title,
            category=result.get("category") or "other",
            brand=result.get("brand") or "Unknown",
            generation=result.get("generation") or "",
            msrp_inr=int(result.get("msrp_inr") or 0),
            release_date=str(release),
            confidence=0.75,  # AI-identified, lower than regex match
        )

    except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.debug("AI normalize error: %s", exc)
        return None
