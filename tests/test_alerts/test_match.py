"""Tests for watch-rule matching."""

from __future__ import annotations

from sqlmodel import Session, select

from deal_hunter.alerts.match import match_watches
from deal_hunter.analysis.schemas import DealAnalysis
from deal_hunter.db.engine import get_engine
from deal_hunter.db.ingest import IngestionService
from deal_hunter.db.models import Listing, WatchHit, WatchRule


def _engine(tmp_path):
    return get_engine(tmp_path / "match.db")


def _listing(
    source_id: str,
    title: str = "RTX 3060 12GB for sale",
    price: float = 12000.0,
    location: str | None = "Delhi",
    **kwargs,
) -> Listing:
    return Listing(
        source="reddit",
        source_id=source_id,
        fingerprint=Listing.compute_fingerprint(title, price, location),
        url=f"https://reddit.com/{source_id}",
        title=title,
        price=price,
        category="gpu",
        location=location,
        **kwargs,
    )


def _analysis(score: int = 8) -> DealAnalysis:
    return DealAnalysis(
        canonical_name="NVIDIA GeForce RTX 3060",
        category="gpu",
        brand="NVIDIA",
        asking_price=12000,
        fair_market_low=10000,
        fair_market_high=15000,
        fair_market_mid=12500,
        msrp=29500,
        price_vs_fair_pct=0.0,
        deal_score=score,
        verdict="BUY",
        reasoning="Test",
        red_flags=[],
        confidence=0.9,
    )


class TestMatchWatches:
    def test_query_tokens_must_match(self, tmp_path) -> None:
        engine = _engine(tmp_path)
        svc = IngestionService(engine)
        svc.ingest_batch([_listing("a"), _listing("b", title="Ryzen 5600X")])
        with Session(engine) as session:
            session.add(WatchRule(query="rtx 3060", enabled=True))
            session.commit()
            listings = list(session.exec(select(Listing)).all())

        analyses = {listing.id: _analysis() for listing in listings}
        hits = match_watches(engine, listings, analyses)
        assert len(hits) == 1
        with Session(engine) as session:
            stored = session.exec(select(WatchHit)).all()
            assert len(stored) == 1
            assert stored[0].listing_id == listings[0].id

    def test_max_price_constraint(self, tmp_path) -> None:
        engine = _engine(tmp_path)
        svc = IngestionService(engine)
        svc.ingest_batch([_listing("a", price=20000.0)])
        with Session(engine) as session:
            session.add(WatchRule(query="rtx 3060", max_price=15000.0, enabled=True))
            session.commit()
            listing = session.exec(select(Listing)).first()

        hits = match_watches(engine, [listing], {listing.id: _analysis()})
        assert hits == []

    def test_location_empty_means_any(self, tmp_path) -> None:
        engine = _engine(tmp_path)
        svc = IngestionService(engine)
        svc.ingest_batch([_listing("a", location="Mumbai")])
        with Session(engine) as session:
            session.add(WatchRule(query="rtx 3060", enabled=True))
            session.commit()
            listing = session.exec(select(Listing)).first()

        hits = match_watches(engine, [listing], {listing.id: _analysis()})
        assert len(hits) == 1

    def test_location_must_match_when_set(self, tmp_path) -> None:
        engine = _engine(tmp_path)
        svc = IngestionService(engine)
        svc.ingest_batch([_listing("a", location="Mumbai")])
        with Session(engine) as session:
            session.add(WatchRule(query="rtx 3060", locations="delhi", enabled=True))
            session.commit()
            listing = session.exec(select(Listing)).first()

        hits = match_watches(engine, [listing], {listing.id: _analysis()})
        assert hits == []

    def test_min_score_constraint(self, tmp_path) -> None:
        engine = _engine(tmp_path)
        svc = IngestionService(engine)
        svc.ingest_batch([_listing("a")])
        with Session(engine) as session:
            session.add(WatchRule(query="rtx 3060", min_score=9, enabled=True))
            session.commit()
            listing = session.exec(select(Listing)).first()

        hits = match_watches(engine, [listing], {listing.id: _analysis(score=7)})
        assert hits == []

    def test_dedupes_rule_listing_pairs(self, tmp_path) -> None:
        engine = _engine(tmp_path)
        svc = IngestionService(engine)
        svc.ingest_batch([_listing("a")])
        with Session(engine) as session:
            session.add(WatchRule(query="rtx 3060", enabled=True))
            session.commit()
            listing = session.exec(select(Listing)).first()

        analyses = {listing.id: _analysis()}
        first = match_watches(engine, [listing], analyses)
        second = match_watches(engine, [listing], analyses)
        assert len(first) == 1
        assert second == []
        with Session(engine) as session:
            assert len(session.exec(select(WatchHit)).all()) == 1
