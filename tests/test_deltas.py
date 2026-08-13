"""No-network tests for month-over-month delta computation."""

from __future__ import annotations

import pandas as pd

from vgr_brand_index.deltas import compute


def _row(qid, brand, rank, tier, index):
    return {"qid": qid, "brand": brand, "rank": rank, "tier": tier, "interest_index": index}


def _history():
    prev = [
        _row("Q1", "Nike", 1, "A", 112),
        _row("Q2", "Gucci", 2, "A", 100),
        _row("Q3", "Ganni", 3, "B", 40),
        _row("Q4", "Leaver", 4, "B", 34),   # will fall out next month
    ]
    cur = [
        _row("Q1", "Nike", 1, "A", 114),     # +2
        _row("Q3", "Ganni", 2, "A", 68),     # +28, B -> A
        _row("Q2", "Gucci", 3, "A", 99),     # -1
        _row("Q5", "Newbie", 4, "B", 35),    # new entrant
    ]
    df = pd.DataFrame([{**r, "month": "2026-07"} for r in prev]
                      + [{**r, "month": "2026-08"} for r in cur])
    return df


def test_baseline_when_no_prior():
    df = pd.DataFrame([{**_row("Q1", "Nike", 1, "A", 114), "month": "2026-08"}])
    d = compute(df, "2026-08")
    assert not d.has_prior
    assert d.winner.brand == "Nike"
    assert d.winner.index_delta is None


def test_winner_growth_and_movers():
    d = compute(_history(), "2026-08")
    assert d.has_prior and d.prev_month == "2026-07"
    assert d.winner.brand == "Nike"
    assert d.winner.index_delta == 2.0
    # Ganni is the sharpest riser (+28)
    assert d.top_risers[0].brand == "Ganni"
    assert d.top_risers[0].index_delta == 28.0


def test_tier_and_membership_migration():
    d = compute(_history(), "2026-08")
    assert "Ganni" in [m.brand for m in d.entered_a]     # B -> A
    assert "Newbie" in [m.brand for m in d.entered_500]  # brand-new
    assert "Leaver" in [m.brand for m in d.left_500]     # fell out
