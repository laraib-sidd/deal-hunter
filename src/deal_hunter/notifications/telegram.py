"""Telegram deal alerts — lightweight, no heavy library needed."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from deal_hunter.analysis.schemas import DealAnalysis

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


def _score_bar(score: int) -> str:
    """Visual score bar using block characters."""
    filled = "\u2588" * score          # █
    empty = "\u2591" * (10 - score)    # ░
    return f"{filled}{empty}"


def _verdict_badge(verdict: str) -> str:
    """Rich verdict label with emoji."""
    badges = {
        "BUY": "\U0001f7e2 BUY NOW",          # 🟢
        "NEGOTIATE": "\U0001f7e1 NEGOTIATE",   # 🟡
        "PASS": "\U0001f534 PASS",             # 🔴
        "SCAM_RISK": "\u26d4 SCAM RISK",       # ⛔
    }
    return badges.get(verdict, verdict)


def _format_deal_message(analysis: DealAnalysis, listing_url: str = "") -> str:
    """Format a deal analysis as a beautiful Telegram HTML message."""
    badge = _verdict_badge(analysis.verdict)
    bar = _score_bar(analysis.deal_score)

    # Price comparison arrow
    if analysis.price_vs_fair_pct < -5:
        price_indicator = f"\u2b07 {abs(analysis.price_vs_fair_pct):.0f}% below market"  # ⬇
    elif analysis.price_vs_fair_pct > 5:
        price_indicator = f"\u2b06 {analysis.price_vs_fair_pct:.0f}% above market"  # ⬆
    else:
        price_indicator = "\u2194 At market price"  # ↔

    # Build the message
    lines = [
        f"{'=' * 28}",
        f"<b>{badge}</b>",
        f"{'=' * 28}",
        "",
        f"\U0001f4e6 <b>{analysis.canonical_name}</b>",
    ]

    if analysis.generation:
        lines.append(f"\U0001f3f7 {analysis.generation} \u2022 {analysis.category.upper()}")
    else:
        lines.append(f"\U0001f3f7 {analysis.category.upper()}")

    lines.extend([
        "",
        f"\U0001f4b0 <b>₹{analysis.asking_price:,}</b>  \u2190 asking",
        f"\U0001f4ca ₹{analysis.fair_market_low:,} \u2013 ₹{analysis.fair_market_high:,}  \u2190 fair range",
        f"\U0001f4c9 {price_indicator}",
        "",
        f"\u2b50 <b>{analysis.deal_score}/10</b>  {bar}",
    ])

    if analysis.suggested_offer:
        lines.append(f"\U0001f4ac Suggest: offer ₹{analysis.suggested_offer:,}")

    # Reasoning
    lines.extend([
        "",
        f"\U0001f9e0 <i>{analysis.reasoning}</i>",
    ])

    # Red flags
    if analysis.red_flags:
        lines.append("")
        severity_icon = {"low": "\u26a0\ufe0f", "medium": "\u26a0\ufe0f", "high": "\u2757", "critical": "\U0001f6a8"}
        for flag in analysis.red_flags[:3]:
            icon = severity_icon.get(flag.severity, "\u26a0\ufe0f")
            lines.append(f"{icon} <b>{flag.severity.upper()}</b>: {flag.detail}")

    # Link
    if listing_url:
        lines.extend([
            "",
            f"\U0001f517 <a href=\"{listing_url}\">View Listing \u2192</a>",
        ])

    return "\n".join(lines)


def _format_summary_message(
    total_scraped: int,
    deals_found: int,
    top_deals: list[DealAnalysis],
) -> str:
    """Format the scrape summary as a beautiful Telegram HTML message."""
    now = datetime.now().strftime("%d %b %Y, %I:%M %p")

    lines = [
        f"\U0001f4e1 <b>Deal Hunter Report</b>",
        f"\U0001f4c5 {now}",
        f"{'─' * 28}",
        "",
        f"\U0001f50d Scanned: <b>{total_scraped}</b> listings",
        f"\U0001f3af Deals found: <b>{deals_found}</b>",
        "",
    ]

    if not top_deals:
        lines.append("\U0001f634 No notable deals this round. Will check again soon.")
        return "\n".join(lines)

    lines.append("<b>Top Finds:</b>")
    lines.append("")

    for i, deal in enumerate(top_deals[:5], 1):
        verdict_emoji = {
            "BUY": "\U0001f7e2", "NEGOTIATE": "\U0001f7e1",
            "PASS": "\U0001f534", "SCAM_RISK": "\u26d4",
        }.get(deal.verdict, "\u2753")

        lines.append(
            f"{i}. {verdict_emoji} <b>{deal.canonical_name}</b>\n"
            f"   ₹{deal.asking_price:,} \u2022 {deal.deal_score}/10 \u2022 {deal.verdict}"
        )

    lines.extend([
        "",
        f"{'─' * 28}",
        "\U0001f916 <i>Powered by Deal Hunter + Groq AI</i>",
    ])

    return "\n".join(lines)


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

    message = _format_summary_message(total_scraped, deals_found, top_deals)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False
