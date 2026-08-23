"""Build a single self-contained snapshot page for GitHub Pages / external review.

Output: static_site/index.html (one file, inline CSS), no cross-page navigation that
breaks statically. Each listing card links to its real source URL. Works on GitHub Pages
with zero server — ideal for sharing what we're building.

If no real DB is present (fresh CI), seeds a demo DB with the catalog + sample listings so
the review page is never empty.
"""
# ruff: noqa: E501  (template/CSS lines are intentionally long output)
# ruff: noqa: E741  (short listing-var names are fine inside template comprehensions)
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, col, select

from deal_hunter.db.engine import get_engine
from deal_hunter.db.models import Listing

OUT = Path(__file__).parent.parent / "static_site" / "index.html"

VERDICT_LABEL = {"BUY": "BUY", "NEGOTIATE": "NEGOTIATE", "PASS": "PASS", "SCAM_RISK": "SCAM RISK"}
VERDICT_CLS = {"BUY": "v-buy", "NEGOTIATE": "v-neg", "PASS": "v-pass", "SCAM_RISK": "v-scam"}

CSS = """
:root{--bg:#0d0e0f;--panel:#18191b;--border:rgba(255,255,255,.07);--t1:#f7f8f8;--t2:#b8bec8;--t3:#8a8f98;--t4:#5b5f66;--acc:#7170ff;--good:#34c759;--warn:#ff9f0a;--bad:#ff453a}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--t1);font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:1200px;margin:0 auto;padding:24px}
.topbar{position:sticky;top:0;z-index:9;background:rgba(13,14,15,.9);backdrop-filter:blur(8px);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;padding:12px 24px}
.topbar .brand{font-weight:700;font-size:15px;color:var(--acc)}
.live{display:inline-flex;align-items:center;gap:7px;margin-left:auto;font-size:12px;color:var(--t3);border:1px solid var(--border);border-radius:999px;padding:4px 10px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--good);box-shadow:0 0 0 3px rgba(52,199,89,.18)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px}
.card .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--t4)}
.card .num{font-size:26px;font-weight:700;margin-top:4px;font-family:ui-monospace,Menlo,monospace}
.sec{margin:26px 0}
.sec h2{font-size:13px;text-transform:uppercase;letter-spacing:.07em;color:var(--t4);margin-bottom:12px;border-bottom:1px solid var(--border);padding-bottom:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}
.pcard{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px;text-decoration:none;color:var(--t1);display:flex;flex-direction:column;gap:8px;transition:transform .12s,border-color .12s}
.pcard:hover{transform:translateY(-2px);border-color:rgba(255,255,255,.2)}
.pcard .cat{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--t4)}
.pcard .title{font-size:14px;font-weight:500;line-height:1.4;min-height:40px;color:var(--t1)}
.pcard .price{font-size:19px;font-weight:700;font-family:ui-monospace,Menlo,monospace;color:var(--t1)}
.pcard .meta{font-size:12px;color:var(--t3);display:flex;justify-content:space-between;gap:8px}
.chip{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;width:max-content}
.v-buy{background:rgba(52,199,89,.16);color:#4ade80}
.v-neg{background:rgba(255,159,10,.16);color:#ffc060}
.v-pass{background:rgba(255,69,58,.16);color:#ff8a7a}
.v-scam{background:rgba(255,69,58,.24);color:#ffb3ab}
.chip.none{background:var(--panel);color:var(--t3);border:1px solid var(--border)}
.muted{color:var(--t3)}.faint{color:var(--t4)}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--border);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--border);font-size:13px}
th{color:var(--t4);font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.05em}
td a{color:var(--t1);text-decoration:none}td a:hover{color:var(--acc)}
.badge{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:600}
.badge.src{background:var(--panel);color:var(--t3);border:1px solid var(--border)}
.alt{color:var(--t3);font-size:12px}
.foot{color:var(--t4);font-size:11px;text-align:center;margin-top:30px;padding:16px}
"""


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=True) if s is not None else "—"


def _fmt_price(p) -> str:
    try:
        return f"₹{int(float(p)):,}"
    except (TypeError, ValueError):
        return "—"


def _time_ago(dt) -> str:
    try:
        d = datetime.fromisoformat(dt) if isinstance(dt, str) else dt
        diff = (datetime.now(d.tzinfo) - d).total_seconds()
        if diff < 3600:
            return f"{int(diff//60)}m ago"
        if diff < 86400:
            return f"{int(diff//3600)}h ago"
        return f"{int(diff//86400)}d ago"
    except (TypeError, ValueError):
        return ""


def _ensure_demo(engine) -> None:
    """Seed data so the snapshot isn't empty (fresh CI checkout lacks the live DB).

    First tries the bundled real-data JSON (listings_snapshot.json); if absent, falls
    back to a small demo seed with the catalog.
    """
    from datetime import UTC, datetime

    from sqlalchemy import func

    from deal_hunter.db.catalog import CatalogService

    with Session(engine) as s:
        count = s.exec(select(func.count(Listing.id))).one()
    if count:
        return  # real DB present (local build)

    snapshot_path = Path(__file__).parent.parent / "data" / "listings_snapshot.json"
    if snapshot_path.exists():
        import json

        rows = json.loads(snapshot_path.read_text())

        with Session(engine) as s:
            for r in rows:
                s.add(Listing(
                    source=r.get("source", "web"),
                    source_id=str(r.get("url", "")),
                    fingerprint=Listing.compute_fingerprint(
                        r.get("title", ""), r.get("price"), r.get("location")
                    ),
                    url=r.get("url", ""),
                    title=r.get("title", ""),
                    price=r.get("price"),
                    category=r.get("category", "other"),
                    canonical_name=r.get("canonical_name"),
                    location=r.get("location"),
                    scraped_at=datetime.fromisoformat(r["scraped_at"]) if r.get("scraped_at") else datetime.now(UTC),
                    deal_verdict=r.get("deal_verdict"),
                    deal_score=r.get("deal_score"),
                ))
            s.commit()
        print(f"Seeded {len(rows)} real listings from bundled snapshot")
        return

    # Fallback: catalog + a couple of demo listings
    CatalogService(engine).seed_from_json()
    now = datetime.now(UTC)
    demo = [
        Listing(source="techenclave", source_id="d1", fingerprint="d1",
                url="https://techenclave.com/t/wts-rtx-3080/1", title="NVIDIA GeForce RTX 3080 10GB",
                price=25000.0, category="gpu", canonical_name="NVIDIA GeForce RTX 3080",
                scraped_at=now, status="active", deal_verdict="NEGOTIATE", deal_score=6),
        Listing(source="reddit", source_id="d2", fingerprint="d2",
                url="https://reddit.com/r/hwswapindia/comments/d2", title="AMD Ryzen 5 5600X",
                price=12000.0, category="cpu", canonical_name="AMD Ryzen 5 5600X",
                scraped_at=now, status="active", deal_verdict="BUY", deal_score=8),
    ]
    with Session(engine) as s:
        s.add_all(demo)
        s.commit()


def _all_listings(engine, limit: int) -> list[Listing]:
    from deal_hunter.scrapers.reddit import _is_spam_post

    with Session(engine) as session:
        # Pull broadly (priced + not spam) across the DB, newest first.
        stmt = (
            select(Listing)
            .where(Listing.price.is_not(None))
            .order_by(col(Listing.scraped_at).desc())
            .limit(limit)
        )
        all_l = list(session.exec(stmt).all())
    clean = [l for l in all_l if not _is_spam_post(l.title, l.description or "")]
    # Stable sort: canonical (real hardware) first, then by recency of scraped_at.
    clean.sort(key=lambda l: (not bool(l.canonical_name), -((l.scraped_at or datetime.min).timestamp())))
    return clean


def _render(engine, limit: int = 200, fetch_limit: int = 1200) -> str:
    listings = _all_listings(engine, fetch_limit)[:limit]
    priced = [l for l in listings if l.price]
    deals = sorted([l for l in priced if l.deal_score], key=lambda l: (-(l.deal_score or 0), l.price or 0))[:12]

    with Session(engine) as s:
        from sqlalchemy import func

        total = s.exec(select(func.count(Listing.id))).one()
        priced_n = s.exec(select(func.count(Listing.id)).where(Listing.price.is_not(None))).one()
        by_src = s.exec(select(Listing.source, func.count(Listing.id)).group_by(Listing.source).order_by(func.count(Listing.id).desc())).all()

    cats = ["gpu", "cpu", "ram", "ssd", "monitor", "motherboard", "psu", "laptop", "other"]

    def card(l: Listing) -> str:
        cat = (l.category or "other").title()
        verdict = l.deal_verdict or "none"
        chip_cls = VERDICT_CLS.get(verdict, "none")
        chip_lbl = VERDICT_LABEL.get(verdict, "—" if verdict == "none" else verdict)
        title = l.canonical_name or l.title or ""
        loc = _esc(l.location)
        src = l.source
        score = f" · {l.deal_score}/10" if l.deal_score else ""
        return (
            f'<a class="pcard" href="{_esc(l.url)}" target="_blank" rel="noopener">'
            f'<div class="cat">{cat} · <span class="badge src">{src}</span></div>'
            f'<div class="title">{_esc(title)}</div>'
            f'<div class="price">{_fmt_price(l.price)}</div>'
            f'<div class="meta"><span>{_esc(loc)}</span><span class="faint">{_time_ago(l.scraped_at)}</span></div>'
            f'<div><span class="chip {chip_cls}">{chip_lbl}</span>{score}</div>'
            f"</a>"
        )

    # Hero stats
    src_rows = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)">'
        f'<span>{_esc(s)}</span><span class="muted">{n}</span></div>'
        for s, n in by_src
    )
    # Deals section
    deal_cards = "".join(card(l) for l in deals) or "<p class='alt'>No scored deals yet.</p>"
    # Marketplace grid grouped by category
    grid_html = ""
    for cat in cats:
        group = [l for l in priced if (l.category or "other") == cat]
        if not group:
            continue
        grid_html += f'<div class="sec"><h2>{cat.title()} <span class="faint">· {len(group)}</span></h2><div class="grid">{"".join(card(l) for l in group[:24])}</div></div>'

    # Full table (recent 60)
    table_rows = "".join(
        f"<tr><td><a href=\"{_esc(l.url)}\" target=\"_blank\">{_esc(l.title or '')[:70]}</a></td>"
        f"<td>{_fmt_price(l.price)}</td><td><span class='badge src'>{_esc(l.source)}</span></td>"
        f"<td><span class='chip {VERDICT_CLS.get(l.deal_verdict,'none')}'>{VERDICT_LABEL.get(l.deal_verdict,'—')}</span></td>"
        f"<td class='faint'>{_time_ago(l.scraped_at)}</td></tr>"
        for l in listings[:60]
    )

    now_str = datetime.now().strftime("%d %b %Y, %H:%M")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Deal Hunter — Used Hardware Deals India (Snapshot)</title>
<style>{CSS}</style></head>
<body>
<div class="topbar">
  <span class="brand">◉ Deal Hunter</span>
  <span class="muted">Used hardware deals · India</span>
  <span class="live"><span class="dot"></span> Live snapshot · {now_str}</span>
</div>
<div class="wrap">

  <div class="cards">
    <div class="card"><div class="lbl">Tracked listings</div><div class="num">{total}</div></div>
    <div class="card"><div class="lbl">Priced</div><div class="num">{priced_n}</div></div>
    <div class="card"><div class="lbl">In this view</div><div class="num">{len(listings)}</div></div>
    <div class="card"><div class="lbl">Sources</div><div class="num">{len(by_src)}</div></div>
  </div>

  <div class="sec"><h2>⭐ Flagged deals (auto-scored)</h2><div class="grid">{deal_cards}</div></div>

  {"".join(grid_html)}

  <div class="sec"><h2>By source</h2>{src_rows}</div>

  <div class="sec"><h2>Recent listings</h2>
    <table><thead><tr><th>Listing</th><th>Price</th><th>Source</th><th>Verdict</th><th>Age</th></tr></thead>
    <tbody>{table_rows}</tbody></table>
  </div>

  <div class="foot">Deal Hunter snapshot for external review · every title links to its real source listing · built {now_str}</div>
</div>
</body></html>"""


def build(limit: int = 200, fetch_limit: int = 1200) -> Path:
    """Build the single-page snapshot. fetch_limit > limit so spam filtering still yields
    `limit` real listings."""
    engine = get_engine()
    _ensure_demo(engine)
    html_str = _render(engine, limit=limit, fetch_limit=fetch_limit)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html_str, encoding="utf-8")
    print(f"Wrote {OUT.resolve()} ({len(html_str) // 1024} KB)")
    return OUT


if __name__ == "__main__":
    build()
