"""Telegram deal alerts — lightweight, no heavy library needed."""

from __future__ import annotations

import logging

import httpx

from deal_hunter.analysis.schemas import DealAnalysis

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


def _format_deal_message(analysis: DealAnalysis, listing_url: str = "") -> str:
    """Format a deal analysis as a Telegram HTML message."""
    score_emoji = {
        "BUY": "🟢",
        "NEGOTIATE": "🟡",
        "PASS": "🔴",
        "SCAM_RISK": "⛔",
    }.get(analysis.verdict, "❓")

    flags_text = ""
    if analysis.red_flags:
        flag_lines = [f"  ⚠️ {f.detail}" for f in analysis.red_flags[:3]]
        flags_text = "\n".join(flag_lines)

    url_line = f'\n🔗 <a href="{listing_url}">View Listing</a>' if listing_url else ""

    return f"""{score_emoji} <b>{analysis.verdict}</b> — {analysis.canonical_name}

💰 Asking: ₹{analysis.asking_price:,}
📊 Fair: ₹{analysis.fair_market_low:,} – ₹{analysis.fair_market_high:,}
📈 Score: {analysis.deal_score}/10

{analysis.reasoning}
{flags_text}{url_line}"""


async def send_deal_alert(
    bot_token: str,
    chat_id: str,
    analysis: DealAnalysis,
    listing_url: str = "",
) -> bool:
    """Send a deal alert to Telegram. Returns True on success."""
    if not bot_token or not chat_id:
        logger.debug("Telegram not configured — skipping alert")
        return False

    message = _format_deal_message(analysis, listing_url)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )

        if resp.status_code == 200:
            logger.info("Telegram alert sent for %s", analysis.canonical_name)
            return True

        logger.error("Telegram API returned %d: %s", resp.status_code, resp.text[:200])
        return False

    except httpx.HTTPError as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


async def send_summary(
    bot_token: str,
    chat_id: str,
    total_scraped: int,
    deals_found: int,
    top_deals: list[DealAnalysis],
) -> bool:
    """Send a scrape summary to Telegram."""
    if not bot_token or not chat_id:
        return False

    lines = [f"📋 <b>Scrape Complete</b>", f"Found {deals_found} deals out of {total_scraped} listings\n"]
    for deal in top_deals[:5]:
        emoji = "🟢" if deal.verdict == "BUY" else "🟡"
        lines.append(f"{emoji} {deal.canonical_name} — ₹{deal.asking_price:,} ({deal.deal_score}/10)")

    if not top_deals:
        lines.append("No notable deals this round.")

    message = "\n".join(lines)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False
