"""Deal Hunter dashboard — FastAPI + Jinja2, server-rendered.

Runs alongside the bot (both drive off the same local SQLite DB). No SPA; pages are
lightweight HTML with GET forms for filtering.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import func
from sqlmodel import Session, col, select

from deal_hunter.analysis.baseline import get_market_stat
from deal_hunter.dashboard.present import (
    SIDEBAR_CATEGORIES,
    SIDEBAR_VERDICTS,
    category_visual,
    fmt_dt,
    fmt_inr,
    live_run_status,
    price_delta,
    relative_time,
    score_bar,
    sparkline_svg,
    verdict_ui,
)
from deal_hunter.db.engine import get_engine, get_price_history
from deal_hunter.db.models import Listing, Seller
from deal_hunter.db.repo_dash import (
    dash_overview,
    get_watch_rules,
    listings_for_canonical,
    marketplace_listings,
    recent_listings,
    recent_watch_hits,
    source_breakdown,
    top_canonical,
)
from deal_hunter.db.repo_meta import last_run_summary

app = FastAPI(title="Deal Hunter Dashboard")

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def verdict_chip(verdict: str | None) -> Markup:
    label, cls = verdict_ui(verdict)
    return Markup(f'<span class="chip {cls}">{label}</span>')


def score_display(score: float | None) -> Markup:
    return Markup(score_bar(int(score) if score is not None else None))


def status_chip(status: str | None) -> Markup:
    if not status:
        return Markup('<span class="chip chip-neutral">—</span>')
    cls_map = {"active": "chip-buy", "dead": "chip-pass", "suppressed": "chip-neutral", "stale": "chip-negotiate"}
    cls = cls_map.get(status, "chip-neutral")
    return Markup(f'<span class="chip {cls}">{status}</span>')


templates.env.globals["verdict_chip"] = verdict_chip
templates.env.globals["score_display"] = score_display
templates.env.globals["status_chip"] = status_chip
templates.env.globals["fmt_dt"] = fmt_dt
templates.env.globals["fmt_inr"] = fmt_inr
templates.env.globals["verdict_ui"] = verdict_ui
templates.env.globals["sparkline_svg"] = sparkline_svg
templates.env.globals["relative_time"] = relative_time


def cat_emoji(cat: str | None) -> str:
    return category_visual(cat)[1]


def cat_gradient(cat: str | None) -> str:
    return category_visual(cat)[2]


templates.env.globals["cat_emoji"] = cat_emoji
templates.env.globals["cat_gradient"] = cat_gradient

_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def _listing_sort_ts(listing: Listing) -> datetime:
    return listing.last_confirmed_at or listing.scraped_at or datetime.min.replace(tzinfo=UTC)


def _render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("overview", dash_overview(_db()))
    ctx.setdefault("live_status", live_run_status(last_run_summary(_db())))
    return templates.TemplateResponse(request, name, ctx)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _render(
        request,
        "index.html",
        active="index",
        listings=recent_listings(_db(), limit=25),
        sources=source_breakdown(_db()),
        top_canonical=top_canonical(_db()),
        watches=get_watch_rules(_db()),
        hits=recent_watch_hits(_db()),
    )


@app.get("/marketplace", response_class=HTMLResponse)
def marketplace(
    request: Request,
    category: str | None = None,
    verdict: str | None = None,
    source: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    sort: str = "newest",
):
    listings = marketplace_listings(
        _db(),
        category=category,
        verdict=verdict,
        source=source,
        min_price=min_price,
        max_price=max_price,
        sort=sort if sort != "newest" else "score",
    )
    if sort == "newest":
        listings.sort(key=_listing_sort_ts, reverse=True)
    elif sort == "price_low":
        listings.sort(key=lambda item: item.price if item.price is not None else float("inf"))
    elif sort == "price_high":
        listings.sort(key=lambda item: item.price if item.price is not None else float("-inf"), reverse=True)
    elif sort == "score":
        listings.sort(key=lambda item: item.deal_score if item.deal_score is not None else -1, reverse=True)

    return _render(
        request,
        "marketplace.html",
        active="marketplace",
        listings=listings,
        sidebar_categories=SIDEBAR_CATEGORIES,
        sidebar_verdicts=SIDEBAR_VERDICTS,
        selected_cat=category,
        selected_verdict=verdict,
        selected_source=source,
        min_price=min_price,
        max_price=max_price,
        sort=sort,
        sources=source_breakdown(_db()),
    )


@app.get("/deals", response_class=HTMLResponse)
def deals(
    request: Request,
    source: str | None = None,
    verdict: str | None = None,
    q: str | None = None,
):
    db = _db()
    scored_clause = (
        Listing.price.is_not(None),
        Listing.deal_score.is_not(None),
        Listing.deal_score >= 6,
    )
    with Session(db) as session:
        priced_count = session.exec(
            select(func.count(Listing.id)).where(Listing.price.is_not(None))
        ).one()
        scored_total = session.exec(
            select(func.count(Listing.id)).where(*scored_clause)
        ).one()
        stmt = select(Listing).where(*scored_clause).order_by(col(Listing.deal_score).desc()).limit(50)
        if source:
            stmt = stmt.where(Listing.source == source)
        if verdict:
            stmt = stmt.where(Listing.deal_verdict == verdict)
        if q and q.strip():
            needle = f"%{q.strip()}%"
            stmt = stmt.where(
                col(Listing.title).ilike(needle) | col(Listing.canonical_name).ilike(needle)
            )
        pool = list(session.exec(stmt).all())

    rows = []
    for item in pool:
        pct = None
        if item.canonical_name:
            market = get_market_stat(db, item.canonical_name)
            if market and market.median:
                pct = round((item.price - market.median) / market.median * 100, 1)
        label, cls = price_delta(pct)
        rows.append((item, label, cls))

    empty_state = None
    if priced_count == 0:
        empty_state = "no_priced"
    elif not scored_total:
        empty_state = "no_scored"

    return _render(
        request,
        "deals.html",
        active="deals",
        deals=rows,
        sources=source_breakdown(db),
        empty_state=empty_state,
        filter_source=source or "",
        filter_verdict=verdict or "",
        filter_q=q or "",
    )


@app.get("/product/{canonical}", response_class=HTMLResponse)
def product(request: Request, canonical: str):
    db = _db()
    listings = listings_for_canonical(db, canonical)
    if not listings:
        raise HTTPException(status_code=404, detail="Product not found")
    market = get_market_stat(db, canonical)
    price_history = get_price_history(db, canonical, limit=60)

    with Session(db) as session:
        seller_ids = {item.seller_id for item in listings if item.seller_id}
        sellers = list(session.exec(select(Seller).where(Seller.id.in_(seller_ids))).all()) if seller_ids else []

    return _render(
        request,
        "product.html",
        active="product",
        canonical=canonical,
        listings=listings,
        market=market,
        price_history=price_history,
        sellers=sellers,
    )


@app.get("/watch", response_class=HTMLResponse)
def watch(request: Request):
    db = _db()
    hits = recent_watch_hits(db)
    listing_titles: dict[int, str] = {}
    if hits:
        listing_ids = {hit.listing_id for hit in hits}
        with Session(db) as session:
            rows = session.exec(select(Listing).where(Listing.id.in_(listing_ids))).all()
            listing_titles = {row.id: row.canonical_name or row.title for row in rows if row.id is not None}

    return _render(
        request,
        "watch.html",
        active="watch",
        watches=get_watch_rules(db),
        hits=hits,
        listing_titles=listing_titles,
    )


@app.get("/health", response_class=HTMLResponse)
def health():
    db = _db()
    overview = dash_overview(db)
    last = last_run_summary(db)
    body = (
        "ok — "
        f"listings={overview['total']} "
        f"sellers={overview['sellers']} "
        f"watches={overview['watches']}"
    )
    if last:
        body += (
            f"\nlast_run: {last['source']} scraped={last['scraped']} "
            f"failed={last['failed']} circuit={last['circuit_state']} "
            f"ms={last['duration_ms']} ({last['started_at']:%H:%M:%S})"
        )
    else:
        body += "\nlast_run: none yet"
    status_code = 200
    if last is None:
        status_code = 503
    else:
        started = last["started_at"]
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if datetime.now(UTC) - started >= timedelta(hours=3):
            status_code = 503
    return HTMLResponse(f"<pre>{body}</pre>", status_code=status_code)
