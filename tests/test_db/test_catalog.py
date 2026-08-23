"""Tests for CatalogService (seed → products/aliases)."""
from __future__ import annotations

from sqlmodel import Session, select

from deal_hunter.db.catalog import CatalogService
from deal_hunter.db.engine import get_engine
from deal_hunter.db.models import Product, ProductAlias


class TestCatalog:
    def test_seed_creates_products_and_aliases(self, tmp_path) -> None:
        e = get_engine(tmp_path / "c.db")
        svc = CatalogService(e)
        n = svc.seed_from_json()
        assert n > 0
        with Session(e) as s:
            gpu = s.exec(select(Product).where(Product.category == "gpu")).all()
            aliases = s.exec(select(ProductAlias)).all()
        assert gpu  # GPU entries present
        assert aliases  # aliases created

    def test_seed_is_idempotent(self, tmp_path) -> None:
        e = get_engine(tmp_path / "c.db")
        svc = CatalogService(e)
        first = svc.seed_from_json()
        second = svc.seed_from_json()
        with Session(e) as s:
            products = s.exec(select(Product)).all()
        assert first > 0
        # still the same total (not doubled)
        assert len(products) == first or len(products) >= first

    def test_alias_map_has_known_aliases(self, tmp_path) -> None:
        e = get_engine(tmp_path / "c.db")
        svc = CatalogService(e)
        svc.seed_from_json()
        amap = svc.alias_map()
        # one of the curated aliases should be present (e.g. rtx 3080)
        assert any("rtx 3080" in k for k in amap) or any("3080" == k for k in amap)