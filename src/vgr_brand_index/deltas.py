"""Month-over-month change: who won, how they grew, and what moved in the top
and the middle — the material the executive summary is built from.

Everything here is derived from the history store (`store.load_history`); no
figure is invented. When there is no prior month (first ever run), the deltas
are empty and the report simply states the standing without a comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Mover:
    qid: str
    brand: str
    tier: str
    rank: int
    index: float
    prev_index: float | None = None
    prev_rank: int | None = None
    prev_tier: str | None = None

    @property
    def index_delta(self) -> float | None:
        return None if self.prev_index is None else round(self.index - self.prev_index, 1)

    @property
    def rank_delta(self) -> int | None:
        # positive = climbed (rank number went down)
        return None if self.prev_rank is None else int(self.prev_rank - self.rank)


@dataclass
class Deltas:
    month: str
    prev_month: str | None
    n_brands: int
    winner: Mover | None = None
    top_risers: list[Mover] = field(default_factory=list)
    top_fallers: list[Mover] = field(default_factory=list)
    a_movers: list[Mover] = field(default_factory=list)   # top-tier movement
    b_movers: list[Mover] = field(default_factory=list)   # middle-tier movement
    entered_a: list[Mover] = field(default_factory=list)
    left_a: list[Mover] = field(default_factory=list)
    entered_500: list[Mover] = field(default_factory=list)
    left_500: list[Mover] = field(default_factory=list)

    @property
    def has_prior(self) -> bool:
        return self.prev_month is not None


def _mover(row: pd.Series, prev: pd.DataFrame | None) -> Mover:
    m = Mover(
        qid=row["qid"], brand=row["brand"], tier=row["tier"],
        rank=int(row["rank"]), index=float(row["interest_index"]),
    )
    if prev is not None and row["qid"] in prev.index:
        p = prev.loc[row["qid"]]
        m.prev_index = float(p["interest_index"])
        m.prev_rank = int(p["rank"])
        m.prev_tier = str(p["tier"])
    return m


def compute(history: pd.DataFrame, month: str, prev_month: str | None = None,
            top_k: int = 8) -> Deltas:
    """Build the Deltas for `month`, comparing against `prev_month` (or the most
    recent earlier month present in history)."""
    cur = history[history["month"] == month].copy()
    if cur.empty:
        raise ValueError(f"no history rows for month {month}")

    if prev_month is None:
        earlier = sorted(m for m in history["month"].unique() if m < month)
        prev_month = earlier[-1] if earlier else None

    prev_idx = None
    if prev_month is not None:
        prev_idx = history[history["month"] == prev_month].set_index("qid")

    cur = cur.sort_values("rank").reset_index(drop=True)
    movers = [_mover(r, prev_idx) for _, r in cur.iterrows()]
    by_qid = {m.qid: m for m in movers}

    d = Deltas(month=month, prev_month=prev_month, n_brands=len(cur))
    d.winner = movers[0] if movers else None

    if prev_month is None:
        return d

    changed = [m for m in movers if m.index_delta is not None]
    ranked_by_delta = sorted(changed, key=lambda m: m.index_delta, reverse=True)
    d.top_risers = [m for m in ranked_by_delta if m.index_delta > 0][:top_k]
    d.top_fallers = [m for m in reversed(ranked_by_delta) if m.index_delta < 0][:top_k]

    d.a_movers = sorted(
        [m for m in changed if m.tier == "A"], key=lambda m: abs(m.index_delta), reverse=True
    )[:top_k]
    d.b_movers = sorted(
        [m for m in changed if m.tier == "B"], key=lambda m: abs(m.index_delta), reverse=True
    )[:top_k]

    prev_qids = set(prev_idx.index)
    prev_tier = prev_idx["tier"].to_dict()
    d.entered_a = [m for m in movers if m.tier == "A" and prev_tier.get(m.qid) != "A"]
    d.left_a = [
        by_qid.get(q) for q in prev_qids
        if prev_tier.get(q) == "A" and (q not in by_qid or by_qid[q].tier != "A")
    ]
    d.left_a = [m for m in d.left_a if m is not None]
    d.entered_500 = [m for m in movers if m.qid not in prev_qids]
    cur_qids = set(by_qid)
    d.left_500 = [
        Mover(qid=q, brand=str(prev_idx.loc[q, "brand"]), tier="—",
              rank=int(prev_idx.loc[q, "rank"]), index=float(prev_idx.loc[q, "interest_index"]),
              prev_rank=int(prev_idx.loc[q, "rank"]), prev_index=float(prev_idx.loc[q, "interest_index"]))
        for q in prev_qids if q not in cur_qids
    ]
    return d
