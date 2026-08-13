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

import pandas as pd

from .gdelt import GdeltClient
from .pageviews import PageviewsClient
from .trends import TrendsClient
from .universe import UniverseItem


def _pv_all_editions(
    item: UniverseItem, editions: dict[str, str], pv: PageviewsClient, window, cache_only: bool
) -> tuple[int, bool]:
    """(total pageviews across editions, any_edition_cached)."""
    total = 0
    cached = False
    for lang, title in editions.items():
        v = pv.trailing_12mo_total(title, lang, window, cache_only=cache_only)
        total += v
        cached = True  # a returned value (even 0) means the edition was reachable
    return total, cached


def gather_signals(
    items: list[UniverseItem],
    editions_by_qid: dict[str, dict[str, str]],
    pv: PageviewsClient,
    gdelt: GdeltClient | None,
    trends: TrendsClient | None,
    window: tuple[str, str],
    *,
    cache_only: bool = True,
    do_trends: bool = True,
    verbose: bool = False,
) -> pd.DataFrame:
    """Return a DataFrame indexed by qid with the raw signals + eligibility flags.

    Columns: brand, description, sitelinks, en_title, pv_12mo, gdelt_12mo,
    trends_score, elig_pv, elig_gdelt, elig_trends.
    """
    gstart, gend = window
    rows: list[dict] = []
    for n, item in enumerate(items, 1):
        editions = editions_by_qid.get(item.qid, {})
        pv_total, pv_cached = _pv_all_editions(item, editions, pv, window, cache_only)

        gdelt_total: int | None = None
        if gdelt is not None:
            gdelt_total = gdelt.monthly_total(item.label, gstart, gend, cache_only=cache_only)

        rows.append(
            {
                "qid": item.qid,
                "brand": item.label,
                "description": item.description,
                "sitelinks": item.sitelinks,
                "en_title": item.en_title,
                "pv_12mo": pv_total,
                "gdelt_12mo": gdelt_total,
            }
        )
        if verbose and (n % 200 == 0 or n == len(items)):
            print(f"    signals {n}/{len(items)}")

    df = pd.DataFrame(rows).set_index("qid")

    # Trends is batched (anchor-chained), so score every brand label at once.
    trends_by_label: dict[str, float | None] = {}
    if trends is not None and do_trends:
        labels = [i.label for i in items]
        trends_by_label = trends.score_brands(labels, cache_only=cache_only)
    df["trends_score"] = df["brand"].map(lambda b: trends_by_label.get(b))

    # Eligibility: a source counts for a brand only when it returned a real value.
    df["elig_pv"] = (df["pv_12mo"].fillna(0) > 0)
    df["elig_gdelt"] = df["gdelt_12mo"].notna()
    df["elig_trends"] = df["trends_score"].notna()
    return df
