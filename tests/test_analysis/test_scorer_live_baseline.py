"""Test that live-market data corrects the fair-value model in scoring (core fix)."""
from __future__ import annotations

from deal_hunter.analysis.normalizer import HardwareNormalizer
from deal_hunter.analysis.scorer import analyze_deal
from deal_hunter.db.engine import get_engine
from deal_hunter.db.models import PriceSnapshot
from sqlmodel import Session


def test_live_baseline_corrects_fair_value(tmp_path) -> None:
    e = get_engine(tmp_path / "t.db")
    # A modern GPU whose MSRP-decay model would undervalue it; inject live snapshots.
    with Session(e) as s:
        s.add(PriceSnapshot(canonical_name="NVIDIA GeForce RTX 3080", price=25000.0))
        s.add(PriceSnapshot(canonical_name="NVIDIA GeForce RTX 3080", price=30000.0))
        s.add(PriceSnapshot(canonical_name="NVIDIA GeForce RTX 3080", price=27000.0))
        s.commit()

    nrm = HardwareNormalizer()
    a = analyze_deal("RTX 3080", asking_price=28000, engine=e, normalizer=nrm)
    assert a is not None
    # live median ~27k should pull fair_market_mid well above the decay-model-only value,
    # so a real 28k listing is NEGOTIATE/within-range, NOT flagged a scam.
    assert a.fair_market_mid > 15000  # decay model alone would put it ~12-15k
    assert a.verdict in ("BUY", "NEGOTIATE", "PASS")