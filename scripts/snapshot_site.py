"""Snapshot the live dashboard to static HTML for GitHub Pages / local preview.

Renders the key routes to .html files in a `static_site/` dir so they can be served as
a static site (no FastAPI needed). Requires the real DB to be present (get_engine()
falls back to ~/.deal-hunter/deals.db).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from deal_hunter.dashboard.app import app

OUT = Path(__file__).parent.parent / "static_site"

# Routes to snapshot. Product page uses a canonical that should exist; skipped if not.
ROUTES = [
    ("index.html", "/"),
    ("marketplace.html", "/marketplace"),
    ("deals.html", "/deals"),
    ("watch.html", "/watch"),
    ("health.txt", "/health"),
]


def _ensure_demo_data() -> None:
    """If no real DB is present (e.g. fresh CI checkout), seed a temp one so the
    snapshot isn't empty. Leaves the real DB untouched."""
    from datetime import UTC, datetime

    from sqlmodel import Session

    from deal_hunter.db.catalog import CatalogService
    from deal_hunter.db.engine import get_engine
    from deal_hunter.db.models import Listing, PriceSnapshot

    db = Path.home() / ".deal-hunter" / "deals.db"
    if db.exists():
        return  # real data available

    Path.home().joinpath(".deal-hunter").mkdir(parents=True, exist_ok=True)
    engine = get_engine(db)
    CatalogService(engine).seed_from_json()

    now = datetime.now(UTC)
    demo = [
        Listing(source="techenclave", source_id="d1", fingerprint="d1",
                url="https://techenclave.com/d1", title="NVIDIA GeForce RTX 3080 10GB",
                price=25000.0, category="gpu", canonical_name="NVIDIA GeForce RTX 3080",
                scraped_at=now, status="active"),
        Listing(source="reddit", source_id="d2", fingerprint="d2",
                url="https://reddit.com/d2", title="AMD Ryzen 5 5600X",
                price=12000.0, category="cpu", canonical_name="AMD Ryzen 5 5600X",
                scraped_at=now, status="active"),
    ]
    with Session(engine) as s:
        s.add_all(demo)
        s.add(PriceSnapshot(canonical_name="NVIDIA GeForce RTX 3080", price=25000.0,
                            observed_at=now))
        s.commit()


def build_site() -> None:
    _ensure_demo_data()
    OUT.mkdir(exist_ok=True)
    client = TestClient(app)
    for fname, route in ROUTES:
        resp = client.get(route)
        if resp.status_code != 200:
            print(f"  ! {route} -> {resp.status_code} (skipped)")
            continue
        (OUT / fname).write_text(resp.text, encoding="utf-8")
        print(f"  {fname} ({len(resp.text)} bytes)")


if __name__ == "__main__":
    build_site()
    print(f"\nSnapshot written to {OUT.resolve()}")
