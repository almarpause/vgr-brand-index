"""Persisting each monthly 'shot' and the append-only history.

Each run writes a dated snapshot folder (`output/<YYYY-MM>/`) plus a `latest/`
pointer, and upserts the month into `history/index_history.parquet` keyed on
(qid, month) so re-running a month corrects it in place rather than duplicating.
The history is what `deltas.py` reads to follow trends over time.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output"
HISTORY = ROOT / "history"
HISTORY_FILE = HISTORY / "index_history.parquet"

# Columns carried into the history store (per brand, per month).
HISTORY_COLS = [
    "rank", "tier", "interest_index", "qid", "brand", "description",
    "sitelinks", "pv_12mo", "reddit_vol", "gdelt_12mo", "trends_score",
    "breadth", "attention", "sources", "n_wikipedias",
]


def write_snapshot(df_top: pd.DataFrame, month: str, outdir: Path = OUTPUT) -> Path:
    """Write the dated monthly shot (csv + parquet) and refresh the latest pointer."""
    dest = outdir / month
    dest.mkdir(parents=True, exist_ok=True)
    df_top.to_csv(dest / "index_500.csv", index=False, encoding="utf-8")
    df_top.to_parquet(dest / "index_500.parquet", index=False)

    latest = outdir / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    df_top.to_csv(latest / "index_500.csv", index=False, encoding="utf-8")
    (latest / "month.txt").write_text(month, encoding="utf-8")
    return dest


def update_history(df_top: pd.DataFrame, month: str) -> pd.DataFrame:
    """Upsert this month into the append-only history, idempotent on (qid, month)."""
    HISTORY.mkdir(parents=True, exist_ok=True)
    cols = [c for c in HISTORY_COLS if c in df_top.columns]
    snap = df_top[cols].copy()
    snap.insert(0, "month", month)

    if HISTORY_FILE.exists():
        hist = pd.read_parquet(HISTORY_FILE)
        hist = hist[hist["month"] != month]                # drop any prior copy of this month
        hist = pd.concat([hist, snap], ignore_index=True)
    else:
        hist = snap
    hist = hist.sort_values(["month", "rank"]).reset_index(drop=True)
    hist.to_parquet(HISTORY_FILE, index=False)
    return hist


def load_history() -> pd.DataFrame:
    if HISTORY_FILE.exists():
        return pd.read_parquet(HISTORY_FILE)
    return pd.DataFrame()


def months_in_history() -> list[str]:
    hist = load_history()
    if hist.empty:
        return []
    return sorted(hist["month"].unique().tolist())
