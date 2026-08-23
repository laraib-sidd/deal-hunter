"""Deal Hunter dashboard — FastAPI + Jinja2, server-rendered.

Runs alongside the bot (both drive off the same local SQLite DB). No SPA; pages are
lightweight HTML with htmx where tables need refreshing.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from deal_hunter.analysis.baseline import get_market_stat
from deal_hunter.dashboard.present import (
    SIDEBAR_CATEGORIES,
    SIDEBAR_VERDICTS,
    category_visual,
    fmt_dt,
    fmt_inr,
    score_bar,
    verdict_ui,
)
from deal_hunter.db.engine import get_engine
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

app = FastAPI(title="Deal Hunter Dashboard")

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Register design-presentation helpers for templates
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


# Marketplace visual helpers
def cat_emoji(cat: str | None) -> str:
    return category_visual(cat)[1]


def cat_gradient(cat: str | None) -> str:
    return category_visual(cat)[2]


templates.env.globals["cat_emoji"] = cat_emoji
templates.env.globals["cat_gradient"] = cat_gradient

# Single shared engine (SQLite is safe for one-process read/write via SQLModel sessions)
_engine = None


def _db():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def _render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("overview", dash_overview(_db()))
    return templates.TemplateResponse(request, name, ctx)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _render(
        request,
        "index.html",
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
        sort=sort,
    )
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
        sources=source_breakdown(_db()),
    )


@app.get("/deals", response_class=HTMLResponse)
def deals(request: Request):
    from deal_hunter.dashboard.present import price_delta

    listings = [x for x in recent_listings(_db(), limit=100) if x.price is not None]
    # compute delta vs live market median per product (fallback None -> neutral)
    rows = []
    for item in listings:
        pct = None
        if item.canonical_name:
            m = get_market_stat(_db(), item.canonical_name)
            if m and m.median:
                pct = round((item.price - m.median) / m.median * 100, 1)
        label, cls = price_delta(pct)
        rows.append((item, label, cls))
    return _render(
        request,
        "deals.html",
        deals=rows,
        sources=source_breakdown(_db()),
    )


@app.get("/product/{canonical}", response_class=HTMLResponse)
def product(request: Request, canonical: str):
    from sqlmodel import Session, select

    from deal_hunter.db.models import Seller

    db = _db()
    listings = listings_for_canonical(db, canonical)
    if not listings:
        raise HTTPException(status_code=404, detail="Product not found")
    market = get_market_stat(db, canonical)

    # sellers attached to these offers (via listing.seller_id FK)
    with Session(db) as session:
        seller_ids = {item.seller_id for item in listings if item.seller_id}
        sellers = list(session.exec(select(Seller).where(Seller.id.in_(seller_ids))).all()) if seller_ids else []

    return _render(
        request,
        "product.html",
        canonical=canonical,
        listings=listings,
        market=market,
        sellers=sellers,
    )


@app.get("/watch", response_class=HTMLResponse)
def watch(request: Request):
    return _render(request, "watch.html", watches=get_watch_rules(_db()), hits=recent_watch_hits(_db()))


@app.get("/health", response_class=HTMLResponse)
def health():
    from deal_hunter.db.repo_meta import last_run_summary

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
    return HTMLResponse(f"<pre>{body}</pre>")
