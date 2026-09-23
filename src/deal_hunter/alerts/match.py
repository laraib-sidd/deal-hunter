"""Match fresh listings against enabled watch rules."""

from __future__ import annotations

from sqlmodel import Session, select

from deal_hunter.analysis.schemas import DealAnalysis
from deal_hunter.db.models import Listing, WatchHit, WatchRule


def _rule_locations(rule: WatchRule) -> list[str]:
    if not rule.locations:
        return []
    return [loc.strip().lower() for loc in rule.locations.split(";") if loc.strip()]


def _matches_query(rule_query: str, listing: Listing) -> bool:
    tokens = [token for token in rule_query.lower().split() if len(token) >= 2]
    if not tokens:
        return True
    hay = f"{listing.title} {listing.canonical_name or ''}".lower()
    return all(token in hay for token in tokens)


def _matches_location(rule_locations: list[str], listing_location: str | None) -> bool:
    if not rule_locations:
        return True
    if not listing_location:
        return False
    hay = listing_location.lower()
    return any(loc in hay for loc in rule_locations)


def match_watches(
    engine,
    listings: list[Listing],
    analyses: dict[int, DealAnalysis],
) -> list[WatchHit]:
    """Insert one WatchHit per (rule, listing) pair that satisfies every set constraint."""
    new_hits: list[WatchHit] = []

    with Session(engine) as session:
        rules = list(
            session.exec(select(WatchRule).where(WatchRule.enabled == True)).all()  # noqa: E712
        )
        existing = {
            (hit.rule_id, hit.listing_id) for hit in session.exec(select(WatchHit)).all()
        }

        for rule in rules:
            if rule.id is None:
                continue
            rule_locations = _rule_locations(rule)
            for listing in listings:
                if listing.id is None:
                    continue
                key = (rule.id, listing.id)
                if key in existing:
                    continue
                if not _matches_query(rule.query, listing):
                    continue
                if rule.max_price is not None and (
                    listing.price is None or listing.price > rule.max_price
                ):
                    continue
                if not _matches_location(rule_locations, listing.location):
                    continue
                if rule.min_score is not None:
                    analysis = analyses.get(listing.id)
                    if analysis is None or analysis.deal_score < rule.min_score:
                        continue
                hit = WatchHit(rule_id=rule.id, listing_id=listing.id)
                session.add(hit)
                new_hits.append(hit)
                existing.add(key)

        session.commit()

    return new_hits
