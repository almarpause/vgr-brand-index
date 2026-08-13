"""Normalisation and multi-source combination.

Two jobs, kept separate on purpose:

  * Cross-sectional (the level / ABC index) — compare brands to each other at one
    snapshot. Each dynamic source is turned into a bounded, comparable score with
    `sqrt_ratio_to_top5`, then the eligible sources are combined per brand with
    `combine_sources`, renormalising the weights over whatever is eligible so a
    missing source is dropped, never zero-filled.

  * Temporal (momentum / lifecycle) — compare a brand to its own past. `zscore`
    over a trailing window says how unusual a brand's attention is right now
    against its own baseline; `inverse_variance_weights` lets noisier sources
    count for less once enough history exists.

Rule throughout: missing is missing. Eligibility is a per-entity, per-source
boolean; the maths never invents a value for an ineligible source.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRAILING_WEEKS = 104


def sqrt_ratio_to_top5(x: pd.Series) -> pd.Series:
    """sqrt(value) as a ratio to the mean of the signal's top 5.

    sqrt stabilises count data (tames the heavy tail without erasing real
    concentration the way log does); dividing by the top-5 mean puts every
    source on the same 'share of the elite' scale before blending.
    """
    t = np.sqrt(x.astype(float).clip(lower=0))
    top5_mean = t.sort_values(ascending=False).head(5).mean()
    if not top5_mean or np.isnan(top5_mean):
        return t * 0.0
    return t / top5_mean


def zscore(values: pd.Series | np.ndarray, window: int | None = None) -> float:
    """Trailing-window z-score of the LAST point against the preceding baseline.

    Used for momentum: a high positive z means attention is unusually high now
    versus this brand's own history. Returns 0.0 when the baseline is degenerate
    (too few points or zero variance) rather than a spurious spike.
    """
    v = pd.Series(values, dtype=float).dropna()
    if window:
        v = v.tail(window)
    if len(v) < 4:
        return 0.0
    current = v.iloc[-1]
    baseline = v.iloc[:-1]
    sd = baseline.std(ddof=0)
    if sd == 0 or np.isnan(sd):
        return 0.0
    return float((current - baseline.mean()) / sd)


def inverse_variance_weights(
    history: dict[str, pd.Series], sources: list[str]
) -> dict[str, float]:
    """Weight each source by 1 / variance of its (log) series — noisier sources
    count for less. Falls back to equal weights when a source has too little
    history to estimate variance. Weights are normalised to sum to 1.
    """
    raw: dict[str, float] = {}
    for s in sources:
        series = history.get(s)
        if series is None or len(pd.Series(series).dropna()) < 6:
            raw[s] = np.nan
            continue
        logged = np.log1p(pd.Series(series, dtype=float).clip(lower=0))
        var = logged.var(ddof=0)
        raw[s] = (1.0 / var) if (var and not np.isnan(var) and var > 0) else np.nan

    known = {s: w for s, w in raw.items() if not np.isnan(w)}
    if not known:
        # no variance estimates yet — equal weights
        return {s: 1.0 / len(sources) for s in sources}
    # sources without an estimate inherit the mean weight of those that have one
    fill = float(np.mean(list(known.values())))
    filled = {s: known.get(s, fill) for s in sources}
    total = sum(filled.values())
    return {s: w / total for s, w in filled.items()}


def combine_sources(
    scores: dict[str, pd.Series],
    eligible: dict[str, pd.Series],
    weights: dict[str, float] | None = None,
) -> pd.Series:
    """Combine per-source cross-sectional scores into one composite per brand.

    `scores[s]`   — the source's score per brand (aligned index)
    `eligible[s]` — boolean per brand: is this source usable for this brand?
    `weights`     — per-source weight (defaults to equal). Renormalised **per
                    brand** over that brand's eligible sources, so dropping a
                    source reweights the rest rather than zero-filling it.
    """
    sources = list(scores.keys())
    if weights is None:
        weights = {s: 1.0 for s in sources}
    idx = next(iter(scores.values())).index
    score_df = pd.DataFrame({s: scores[s].reindex(idx) for s in sources})
    elig_df = pd.DataFrame({s: eligible[s].reindex(idx).fillna(False) for s in sources})

    w = np.array([weights.get(s, 0.0) for s in sources], dtype=float)
    out = pd.Series(0.0, index=idx)
    for i, brand in enumerate(idx):
        mask = elig_df.iloc[i].to_numpy(dtype=bool)
        if not mask.any():
            out.iloc[i] = np.nan          # no eligible source — honestly missing
            continue
        vals = score_df.iloc[i].to_numpy(dtype=float)
        wv = w * mask
        wsum = wv.sum()
        if wsum == 0:
            out.iloc[i] = np.nan
            continue
        out.iloc[i] = float(np.nansum(np.where(mask, vals, 0.0) * wv) / wsum)
    return out
