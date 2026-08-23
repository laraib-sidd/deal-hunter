"""CatalogService — the scalable product catalog.

The hardware DB moves from an in-memory JSON to SQLite tables (`products`,
`product_aliases`, `product_specs`, `msrp_history`). This service:
- loads a bundled seed (from the legacy JSON) into the DB idempotently,
- exposes an alias→product lookup map for the normalizer,
- lets products be enriched over time (source=curated|bundled|ai) without breaking
  the human-curated anchors.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlmodel import Session, col, select

from deal_hunter.db.models import MsrpHistory, Product, ProductAlias

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_SEED = _DATA_DIR / "hardware_db.json"


def _sluggify(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum() or c in "-_ ").strip().replace(" ", "-")


class CatalogService:
    """Upsert + query products and aliases from the catalog tables."""

    def __init__(self, engine, seed_path: Path = DEFAULT_SEED) -> None:
        self._engine = engine
        self._seed_path = seed_path

    # --- seeding ---
    def seed_from_json(self) -> int:
        """Load the bundled JSON into `products` + `product_aliases` idempotently."""
        if not self._seed_path.exists():
            logger.warning("Catalog seed not found at %s", self._seed_path)
            return 0

        raw = json.loads(self._seed_path.read_text())
        count = 0
        with Session(self._engine) as session:
            for category in ("gpu", "cpu", "ram", "ssd", "monitor", "motherboard", "psu"):
                for entry in raw.get(category, []):
                    hw_id = entry.get("id") or _sluggify(entry["name"])
                    existing = session.exec(
                        select(Product).where(Product.hardware_id == hw_id)
                    ).first()
                    specs_json = json.dumps(entry.get("specs", {}))
                    mining = hw_id in raw.get("mining_popular_gpus", [])

                    if existing:
                        if not existing.msrp_inr:
                            existing.msrp_inr = entry.get("msrp_inr")
                        if not existing.release_date:
                            existing.release_date = entry.get("release_date")
                        if not existing.specs_json:
                            existing.specs_json = specs_json
                        prod = existing
                    else:
                        prod = Product(
                            hardware_id=hw_id,
                            canonical_name=entry["name"],
                            category=category,
                            brand=entry.get("brand", ""),
                            series=entry.get("series", ""),
                            generation=entry.get("generation", ""),
                            release_date=entry.get("release_date"),
                            msrp_inr=entry.get("msrp_inr"),
                            source="curated",
                            confidence=1.0,
                            specs_json=specs_json,
                            mining_popular=mining,
                        )
                        session.add(prod)
                        session.flush()

                    # aliases
                    for alias in entry.get("aliases", []):
                        al = session.exec(
                            select(ProductAlias).where(
                                ProductAlias.product_id == prod.id,
                                ProductAlias.alias == alias.lower(),
                            )
                        ).first()
                        if al is None:
                            session.add(ProductAlias(
                                product_id=prod.id, alias=alias.lower(), confidence=1.0,
                            ))

                    # MsrpHistory
                    if entry.get("msrp_inr"):
                        session.add(MsrpHistory(
                            product_id=prod.id,
                            msrp_inr=entry["msrp_inr"],
                            source="seed",
                        ))
                    count += 1
            session.commit()

        logger.info("Catalog seeded: %d products", count)
        return count

    # --- lookup map for the normalizer ---
    def alias_map(self) -> dict[str, tuple[int, str, str, float]]:
        """Build {alias_lower: (product_id, category, canonical_name, confidence)}."""
        with Session(self._engine) as session:
            rows = session.exec(
                select(ProductAlias, Product)
                .join(Product)
                .order_by(col(ProductAlias.confidence).desc())
            ).all()
            out: dict[str, tuple[int, str, str, float]] = {}
            for alias, prod in rows:
                out[alias.alias] = (prod.id, prod.category, prod.canonical_name, alias.confidence)
            return out

    def find_by_id(self, product_id: int) -> Product | None:
        with Session(self._engine) as session:
            return session.get(Product, product_id)
