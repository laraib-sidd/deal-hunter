"""Tests for dashboard routes (FastAPI TestClient) + marketplace filters."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from deal_hunter.dashboard import app as app_module
from deal_hunter.dashboard.app import app
from deal_hunter.db.engine import get_engine


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    # Point the dashboard at a hermetic temp DB (they share the global engine cache).
    engine = get_engine(tmp_path / "dash.db")
    monkeypatch.setattr(app_module, "_engine", engine)
    return TestClient(app)


class TestDashboardRoutes:
    def test_index_200(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert "Deal Hunter" in r.text

    def test_marketplace_200(self, client: TestClient) -> None:
        r = client.get("/marketplace")
        assert r.status_code == 200
        assert "item" in r.text.lower() or "no listings" in r.text.lower()

    def test_marketplace_category_filter(self, client: TestClient) -> None:
        r = client.get("/marketplace?category=gpu")
        assert r.status_code == 200

    def test_deals_200(self, client: TestClient) -> None:
        r = client.get("/deals")
        assert r.status_code == 200

    def test_watch_200(self, client: TestClient) -> None:
        r = client.get("/watch")
        assert r.status_code == 200

    def test_health_200(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code == 200

    def test_unknown_product_404(self, client: TestClient) -> None:
        r = client.get("/product/definitely-not-a-real-product-xyz")
        assert r.status_code == 404
