"""Telegram bot — interactive query + watch management against the local DB.

Commands:
  /start, /help
  free-text query:  "rtx 3060 under 15000 in Delhi"   (live ranked reply)
  /watch <query under <max>>   create a persistent watch
  /watches                    list active watches
  /unwatch <id>               disable a watch
"""
from __future__ import annotations

import logging
import re

from sqlmodel import Session, col, select
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from deal_hunter.db.engine import get_engine
from deal_hunter.db.models import Listing, WatchRule

logger = logging.getLogger(__name__)

_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def human_price(p: float | None) -> str:
    return f"₹{p:,.0f}" if p is not None else "—"


# ------------------------------- query parsing ------------------------------
_DROP_TOKENS = {"in", "under", "below", "less", "than", "max", "rs", "rupees",
                "inr", "for", "the", "a", "there", "delhi/ncr", "at"}


def parse_query(text: str) -> tuple[str, float | None, list[str]]:
    """Parse "rtx 3060 under 15k in delhi" -> (keywords, max_price, locations).

    Supports: "under 15000", "under 15k", "below ₹20,000", bare "15000".
    """
    lowered = text.lower()

    # 1) max price — prefer explicit "under/below $X [k]"
    max_price: float | None = None
    um = re.search(
        r"(?:under|below|less than|max|<=)\s*(?:₹|rs\.?|inr)?\s*([\d,]+)\s*(k)?", lowered
    )
    if um:
        base = int(um.group(1).replace(",", ""))
        if um.group(2):  # trailing 'k'
            base *= 1000
        max_price = float(base)
    else:
        nm = re.match(r"(?:₹|rs\.?|inr)?\s*([\d,]+)\s*(k)?\b", lowered)
        if nm and nm.start() == 0 and nm.group(1):
            base = int(nm.group(1).replace(",", ""))
            if nm.group(2):
                base *= 1000
            max_price = float(base)

    # 2) locations (trailing "in <city>")
    locations: list[str] = []
    loc_m = re.search(r"\bin\s+([a-z /]+?)\s*$", lowered)
    if loc_m:
        for tok in loc_m.group(1).split():
            t = re.sub(r"[^a-z]", "", tok)
            if t and t not in {"in"}:
                locations.append(t)

    # 3) keywords = drop price span + location tokens
    work = lowered
    for loc in locations:
        work = re.sub(rf"\b{re.escape(loc)}\b", " ", work)
    if um is not None:
        work = work[: um.start()] + " " + work[um.end():]
    else:
        nm = re.match(r"^[\s]*(?:₹|rs\.?|inr)?[\s]*[\d,]+(\s*k|thousand)?\b", work)
        if nm and nm.end() > 0:
            work = work[nm.end():]

    tokens = [t for t in re.split(r"\W+", work) if t and t not in _DROP_TOKENS]
    keywords = " ".join(tokens).strip()
    return (keywords or text.strip()), max_price, locations


# ------------------------------- search + format
def search_listings(
    engine,
    keywords: str,
    max_price: float | None,
    limit: int = 6,
    locations: list[str] | None = None,
) -> list[Listing]:
    with Session(engine) as session:
        stmt = select(Listing).where(Listing.status == "active")
        if max_price is not None:
            stmt = stmt.where(Listing.price.is_not(None), Listing.price <= max_price)
        stmt = stmt.order_by(col(Listing.scraped_at).desc()).limit(300)
        rows = list(session.exec(stmt).all())

    if locations:
        locs = [loc.lower() for loc in locations if loc]
        rows = [
            row
            for row in rows
            if row.location and any(loc in row.location.lower() for loc in locs)
        ]

    kws = [k for k in keywords.lower().split() if len(k) >= 2]
    if not kws:
        return rows[:limit]

    def match(row: Listing) -> int:
        hay = f"{row.title} {row.description or ''}".lower()
        return sum(1 for k in kws if k in hay)

    scored = [(row, match(row)) for row in rows]
    scored = [p for p in scored if p[1] > 0]
    scored.sort(key=lambda p: (-p[1], p[0].price or 0))
    return [row for row, _ in scored[:limit]]


def fmt_result(i: int, row: Listing) -> str:
    badge = ""
    if row.deal_verdict:
        badge = f" [{row.deal_verdict}]{'★' if row.deal_score is not None and row.deal_score >= 6 else ''}"
    loc = f" · {row.location}" if row.location else ""
    return f"{i}. {row.title[:80]}\n   {human_price(row.price)} — {row.source}{loc}{badge}"


# ------------------------------- PTB handlers
async def cmd_start(update: Update, _ctx) -> None:
    await update.message.reply_text(
        "🎯 Deal Hunter\n\n"
        "Send a query like:\n"
        "  rtx 3060 under 15000 in delhi\n"
        "  ryzen laptop in mumbai\n\n"
        "Commands:\n"
        "/watch rtx 3060 under 15k  — create a live watch\n"
        "/watches — list  ·  /unwatch <id> — remove"
    )


async def cmd_watch(update: Update, _ctx) -> None:
    arg = update.message.text.replace("/watch", "", 1).strip()
    if not arg:
        await update.message.reply_text("Usage: /watch rtx 3060 under 15k")
        return
    keywords, max_price, locations = parse_query(arg)
    with Session(_db()) as session:
        rule = WatchRule(
            label=arg,
            query=keywords or arg,
            max_price=max_price,
            locations=(";".join(locations)) or None,
            kind="query",
            enabled=True,
        )
        session.add(rule)
        session.commit()
        rid = rule.id
    await update.message.reply_text(
        f"✅ Watching: {keywords or arg}" + (f" under ₹{max_price:,.0f}" if max_price else "") + f" (watch #{rid})"
    )


async def cmd_watches(update: Update, _ctx) -> None:
    with Session(_db()) as session:
        rules = list(
            session.exec(
                select(WatchRule).where(WatchRule.enabled == True).order_by(WatchRule.created_at.desc())  # noqa: E712
            ).all()
        )
    if not rules:
        await update.message.reply_text("No active watches. /watch something.")
        return
    lines = [
        f"{r.id}. {r.label} → {human_price(r.max_price) if r.max_price else 'any price'}"
        for r in rules
    ]
    await update.message.reply_text("Active watches:\n" + "\n".join(lines))


async def cmd_unwatch(update: Update, _ctx) -> None:
    parts = update.message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await update.message.reply_text("Usage: /unwatch <id>")
        return
    with Session(_db()) as session:
        rule = session.get(WatchRule, int(parts[1]))
        if rule:
            rule.enabled = False
            session.commit()
            await update.message.reply_text(f"Disabled watch #{rule.id}")
        else:
            await update.message.reply_text("Watch not found")


async def on_message(update: Update, _ctx) -> None:
    text = (update.message.text or "").strip()
    if not text:
        return
    keywords, max_price, locations = parse_query(text)
    try:
        results = search_listings(_db(), keywords, max_price, locations=locations)
    except Exception:
        logger.exception("query failed")
        await update.message.reply_text("⚠️ Something broke — try again.")
        return
    if not results:
        await update.message.reply_text("Nothing found. Try a different name or raise the budget.")
        return
    header = f"<b>{keywords}</b>" + (f" under <b>₹{max_price:,.0f}</b>" if max_price else "")
    body = "\n\n".join(fmt_result(i, row) for i, row in enumerate(results, 1))
    await update.message.reply_text(header + "\n\n" + body, parse_mode="HTML")


def build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("watches", cmd_watches))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app


async def run_bot(token: str) -> None:
    """Run the polling bot (blocking)."""
    app = build_app(token)
    logger.info("Starting Deal Hunter bot polling...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("Bot is running (Ctrl+C to stop)")
    try:
        while True:
            import asyncio

            await asyncio.sleep(3600)
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
