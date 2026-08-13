"""Gather the per-brand attention signals into one table.

One function, two modes:
  * `cache_only=True`  — the scoring pass. Reads only what the nightly fetches
    have already cached; a brand missing a source is simply flagged ineligible.
  * `cache_only=False` — the fetch pass. Actually hits the APIs (used by
    fetch_nightly on one shard at a time, so it stays gentle).

Signals: Wikipedia pageviews summed across all editions, GDELT monthly news
volume, and Google Trends search interest. Eligibility is explicit per source so
the composite can renormalise over what is available — missing is missing.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

import pandas as pd

from .gdelt import GdeltClient
from .pageviews import PageviewsClient
from .trends import TrendsClient
from .universe import UniverseItem


def _pv_monthly(
    editions: dict[str, str], pv: PageviewsClient, window, cache_only: bool
) -> dict[str, int]:
    """All-edition pageviews per calendar month: {YYYY-MM: total views}."""
    monthly: dict[str, int] = defaultdict(int)
    for lang, title in editions.items():
        for ts, v in pv.fetch(title, lang, window[0], window[1], "monthly", cache_only=cache_only):
            monthly[ts[:7]] += v
    return monthly


def pv_stats(monthly: dict[str, int]) -> tuple[int, float, int]:
    """(median monthly, recent-3-month mean, 12-month total) from the series.

    The MEDIAN is the level signal — robust to one-off spikes (a designer's death,
    a scandal, a viral collab) that a 12-month sum would bank as lasting attention.
    """
    series = [monthly[k] for k in sorted(monthly)]
    if not series:
        return 0, 0.0, 0
    median = int(statistics.median(series))
    recent = statistics.mean(series[-3:]) if len(series) >= 3 else statistics.mean(series)
    return median, round(recent, 1), sum(series)


def gather_signals(
    items: list[UniverseItem],
    editions_by_qid: dict[str, dict[str, str]],
    pv: PageviewsClient,
    gdelt: GdeltClient | None,
    trends: TrendsClient | None,
    window: tuple[str, str],
    *,
    reddit=None,
    cache_only: bool = True,
    do_trends: bool = True,
    verbose: bool = False,
) -> pd.DataFrame:
    """Return a DataFrame indexed by qid with the raw signals + eligibility flags.

    Columns: brand, description, sitelinks, en_title, pv_12mo, gdelt_12mo,
    reddit_vol, trends_score, elig_pv/gdelt/reddit/trends.
    """
    gstart, gend = window
    rows: list[dict] = []
    for n, item in enumerate(items, 1):
        editions = editions_by_qid.get(item.qid, {})
        monthly = _pv_monthly(editions, pv, window, cache_only)
        pv_median, pv_recent, pv_total = pv_stats(monthly)

        gdelt_total: int | None = None
        if gdelt is not None:
            gdelt_total = gdelt.monthly_total(item.label, gstart, gend, cache_only=cache_only)

        reddit_vol: int | None = None
        if reddit is not None:
            reddit_vol = reddit.fetch(item.label, cache_only=cache_only)

        rows.append(
            {
                "qid": item.qid,
                "brand": item.label,
                "description": item.description,
                "sitelinks": item.sitelinks,
                "en_title": item.en_title,
                "pv_median": pv_median,
                "pv_recent": pv_recent,
                "pv_12mo": pv_total,
                "gdelt_12mo": gdelt_total,
                "reddit_vol": reddit_vol,
            }
        )
        if verbose and (n % 200 == 0 or n == len(items)):
            print(f"    signals {n}/{len(items)}")

    df = pd.DataFrame(rows).set_index("qid")

    # Trends is batched (anchor-chained). Batch in pageviews-descending order so
    # the highest-attention brands land in the earliest batches (fetched first)
    # and the batch/cache keys are stable across runs.
    trends_by_label: dict[str, float | None] = {}
    if trends is not None and do_trends:
        labels_pv_desc = df.sort_values("pv_12mo", ascending=False)["brand"].tolist()
        trends_by_label = trends.score_brands(labels_pv_desc, cache_only=cache_only)
    df["trends_score"] = df["brand"].map(lambda b: trends_by_label.get(b))

    # Eligibility: a source counts for a brand only when it returned a real value.
    df["elig_pv"] = (df["pv_median"].fillna(0) > 0)
    df["elig_gdelt"] = df["gdelt_12mo"].notna()
    df["elig_trends"] = df["trends_score"].notna()
    df["elig_reddit"] = df["reddit_vol"].notna()
    return df
