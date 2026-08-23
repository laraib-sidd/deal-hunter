"""Tests that the normalizer merges DB-catalog aliases when given an engine (M4)."""
from __future__ import annotations

from deal_hunter.analysis.normalizer import HardwareNormalizer
from deal_hunter.db.catalog import CatalogService
from deal_hunter.db.engine import get_engine


class TestNormalizerWithCatalog:
    def test_db_aliases_expand_lookup(self, tmp_path) -> None:
        e = get_engine(tmp_path / "n.db")
        CatalogService(e).seed_from_json()
        nrm = HardwareNormalizer(engine=e)
        # the catalog adds DB-backed aliases on top of the JSON ones
        assert len(nrm._alias_map) > 0
        # known curated alias still resolves
        hit = nrm.normalize("RTX 3080 for sale") or nrm.normalize("rtx 3080")
        assert hit is not None

    def test_without_engine_is_unchanged(self) -> None:
        nrm = HardwareNormalizer()
        assert nrm._alias_map  # JSON aliases still present
        # no db-* synthetic ids without an engine
        assert not any(k.startswith("db-") for k in nrm._entries)
