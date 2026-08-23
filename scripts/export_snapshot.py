"""Export a representative slice of the real DB to a committed JSON for the Pages build.

Generates data/listings_snapshot.json (real scraped listings, spam-filtered, real URLs)
so the GitHub Pages CI build renders genuine hardware even without access to the live DB.
"""
# ruff: noqa: E501, E741  (build script — template/data lines are intentionally long)
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, col, select

from deal_hunter.db.engine import get_engine
from deal_hunter.db.models import Listing

OUT = Path(__file__).parent.parent / "data" / "listings_snapshot.json"

# Strict spam detection for the SNAPSHOT (production regex is deliberately conservative).
# Catches "[H] .. [W] UPI" trades and upi/voucher ratios that leak through the lenient one.
_SNAPSHOT_SPAM = re.compile(
    r"\[h\]|\[w\]|\bupi\b|\bupi/|\bupto\s+\d+%"
    r"|\b(?:gift\s*card|voucher|\bgc\b|paytm\s*cash)\b"
    r"|\b\d+\s*%?\s*(?:upi|gc|gv)\b",
    re.IGNORECASE,
)


def _is_snapshot_spam(title: str) -> bool:
    return bool(_SNAPSHOT_SPAM.search(title or ""))


def export(limit: int = 300, fetch: int = 2000) -> Path:
    from deal_hunter.scrapers.reddit import _is_spam_post

    eng = get_engine()
    with Session(eng) as s:
        stmt = (
            select(Listing)
            .where(Listing.price.is_not(None))
            .order_by(col(Listing.scraped_at).desc())
            .limit(fetch)
        )
        rows = list(s.exec(stmt).all())
    clean = [
        r for r in rows
        if not _is_spam_post(r.title, r.description or "")
        and not _is_snapshot_spam(r.title)
    ]
    clean.sort(
        key=lambda r: (not bool(r.canonical_name), -((r.scraped_at or datetime.min).timestamp()))
    )

    payload = []
    for l in clean[:limit]:
        payload.append({
            "source": l.source,
            "url": l.url,
            "title": l.title,
            "price": l.price,
            "category": l.category,
            "canonical_name": l.canonical_name,
            "location": l.location,
            "scraped_at": l.scraped_at.isoformat() if l.scraped_at else None,
            "deal_verdict": l.deal_verdict,
            "deal_score": l.deal_score,
        })
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"Exported {len(payload)} real listings -> {OUT.resolve()} ({OUT.stat().st_size // 1024} KB)")
    return OUT


if __name__ == "__main__":
    export()
