"""Rebuild index_500_refreshed.csv after roster surgery (remove/add brands).

Reproduces the Sept-2026 refresh scoring EXACTLY (three sources, 50/30/20):
  score per source  = sqrt_ratio_to_top5(raw)         [normalize.py]
  attention         = combine_sources(.., {trends .50, news .30, pv .20})
  breadth           = sqrt_ratio_to_top5(sitelinks)
  raw               = 0.15*breadth + 0.85*attention
  rank by raw desc; interest_index = raw / top5_mean(raw) * 100; tier from index.

Self-validates: recomputing the UNMODIFIED roster must reproduce the stored
interest_index (max abs diff ~0) before any surgery is trusted.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(r"C:\Users\aresi\Claude\code\brand-index")
sys.path.insert(0, str(ROOT / "src"))
from vgr_brand_index.normalize import sqrt_ratio_to_top5, combine_sources

CSV = ROOT / "refresh_500" / "index_500_refreshed.csv"
WEIGHTS = {"trends": 0.50, "news": 0.30, "pv": 0.20}
SOURCES = ["trends", "news", "pv"]
RAW_COLS = {"trends": "trends_score", "news": "news_score", "pv": "pv_median"}
BREADTH_WEIGHT, ATTENTION_WEIGHT = 0.15, 0.85
MIN_COV = 60


def tier_of(idx: float) -> str:
    return "A" if idx >= 66 else ("B" if idx >= 33 else "C")


def score(df: pd.DataFrame) -> pd.DataFrame:
    """Re-score a roster frame. Requires columns: sitelinks, pv_median,
    trends_score, news_score, elig_pv, elig_trends, elig_news."""
    df = df.reset_index(drop=True).copy()
    scores = {s: sqrt_ratio_to_top5(df[RAW_COLS[s]].astype(float).fillna(0.0)) for s in SOURCES}
    elig = {s: df[f"elig_{s}"].astype(bool) for s in SOURCES}
    for s in SOURCES:                       # coverage gate
        if int(elig[s].sum()) < MIN_COV:
            elig[s] = pd.Series(False, index=df.index)
    for s in SOURCES:
        df[f"{s}_ratio"] = scores[s]
    df["sources"] = ["+".join(s for s in SOURCES if elig[s].iloc[i]) for i in range(len(df))]
    df["attention"] = combine_sources(scores, elig, WEIGHTS)
    df["breadth"] = sqrt_ratio_to_top5(df["sitelinks"].astype(float).fillna(0.0))
    df["raw"] = BREADTH_WEIGHT * df["breadth"] + ATTENTION_WEIGHT * df["attention"].fillna(0.0)
    df = df.sort_values("raw", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    benchmark = df["raw"].head(5).mean()
    df["interest_index"] = (df["raw"] / benchmark * 100).round(1)
    df["tier"] = df["interest_index"].map(tier_of)
    return df


def validate():
    df = pd.read_csv(CSV)
    stored = df.set_index("qid")["interest_index"]
    rebuilt = score(df).set_index("qid")["interest_index"]
    diff = (rebuilt - stored).abs()
    print(f"validation: n={len(df)} max|Δinterest|={diff.max():.4f} "
          f"mismatches>0.05={int((diff>0.05).sum())}")
    # rank check
    sr = score(df).set_index("qid")["rank"]
    orig = df.set_index("qid")["rank"]
    rd = (sr - orig).abs()
    print(f"            max|Δrank|={int(rd.max())} rank mismatches={int((rd>0).sum())}")
    return diff.max()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    validate()
