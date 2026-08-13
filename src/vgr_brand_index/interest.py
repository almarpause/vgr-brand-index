"""Interest scoring, indexing and A/B/C tiering.

Pipeline:
  1. universe   — query the fashion/footwear/sportswear/luxury pool from Wikidata
  2. signals    — per brand: all-language Wikipedia pageviews, GDELT news volume,
                  Google Trends search interest (gathered by signals.gather, read
                  from cache during scoring)
  3. attention  — each dynamic source -> sqrt-ratio-to-top-5, combined by
                  inverse-variance weighting over the ELIGIBLE sources only
  4. blend      — 50/50 of sitelink breadth + the attention composite
  5. index      — scale so the mean blended score of the top 5 brands = 100
  6. tier       — A >= 66, B 33-65, C < 33 on that top-5-anchored scale
  7. cut        — keep the top 500 by interest

Design rule: never invent a figure. A source that returned no value for a brand
is ineligible for that brand and the composite renormalises over the rest —
missing is missing, never zero-filled.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .normalize import combine_sources, sqrt_ratio_to_top5
from .pageviews import PageviewsClient, trailing_12_month_window
from .signals import gather_signals
from .universe import SparqlClient, UniverseItem, fetch_universe
from .wikidata import LANGUAGES, WikidataClient

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache"
OUTPUT = ROOT / "output"

TIER_A_MIN = 66.0   # interest index (top-5 avg = 100)
TIER_B_MIN = 33.0
TOP_N = 500

# A dynamic source must cover at least this many brands to count (guards against
# a near-empty source maxing out a few brands during ramp-up).
MIN_SOURCE_ABS = 60
MIN_SOURCE_FRAC = 0.05

# Wikipedia sitelink breadth is a slow legacy-notability signal, not current
# attention — a small co-factor, not the driver. The attention composite (what
# people actually read, search and read news about) carries the rest.
BREADTH_WEIGHT = 0.15
ATTENTION_WEIGHT = 1.0 - BREADTH_WEIGHT

# Within the attention composite: consumer signals (Reddit buzz, Google search)
# are the best proxies for commercial attention; pageviews next; news noisiest.
# combine_sources renormalises per brand over whichever sources are eligible.
SOURCE_WEIGHTS = {"pv": 0.25, "gdelt": 0.10, "trends": 0.30, "reddit": 0.35}

# The dynamic attention sources that form the composite.
DYNAMIC_SOURCES = ["pv", "gdelt", "trends", "reddit"]

# Parent groups / holding companies. The VGR rule is that global groups are
# decomposed to banners and never appear as their own brand row. We FLAG rather
# than drop, so the exclusion decision stays with the human review.
_KNOWN_GROUPS = {
    "Inditex", "LVMH", "Kering", "Richemont", "Compagnie Financière Richemont",
    "PVH", "VF Corporation", "Tapestry, Inc.", "Capri Holdings", "SMCP Group",
    "OTB Group", "Bestseller", "LPP", "Fast Retailing", "Gap Inc.",
    "Boohoo Group", "Debenhams Group", "Tendam", "AWWG", "About You",
    "Otto GmbH", "Authentic Brands Group",
}
_GROUP_DESC = ("holding", "conglomerate", "fashion group", "parent company", "holdings company")


def review_flag(brand: str, description: str) -> str:
    desc = (description or "").lower()
    if brand in _KNOWN_GROUPS:
        return "GROUP"
    if any(k in desc for k in _GROUP_DESC):
        return "GROUP?"
    return ""


def tier_of(index: float) -> str:
    if index >= TIER_A_MIN:
        return "A"
    if index >= TIER_B_MIN:
        return "B"
    return "C"


def score_universe(signals: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Blend breadth + attention composite, index to the top-5 average, tier.

    `signals` is the DataFrame from signals.gather_signals (indexed by qid):
    sitelinks, pv_12mo, gdelt_12mo, trends_score, elig_pv/gdelt/trends.
    """
    df = signals.copy()

    # Cross-sectional score per dynamic source: sqrt-ratio to that source's top 5.
    raw_cols = {"pv": "pv_12mo", "gdelt": "gdelt_12mo", "trends": "trends_score",
                "reddit": "reddit_vol"}
    scores = {s: sqrt_ratio_to_top5(df[raw_cols[s]].astype(float).fillna(0.0)) for s in DYNAMIC_SOURCES}
    elig = {s: df[f"elig_{s}"].astype(bool) for s in DYNAMIC_SOURCES}

    # Coverage gate: a source only counts once enough brands carry it. With just a
    # handful eligible (ramp-up, or a throttled night), the sqrt-ratio-to-top-5 is
    # taken over a near-empty distribution and those few brands max out, distorting
    # the index. Below the threshold the whole source is held back until the
    # nightly fetch fills it in.
    min_cov = max(MIN_SOURCE_ABS, int(MIN_SOURCE_FRAC * len(df)))
    for s in DYNAMIC_SOURCES:
        if int(elig[s].sum()) < min_cov:
            elig[s] = pd.Series(False, index=df.index)

    # store the normalised per-source ratio under a distinct name — never reuse a
    # raw column name (e.g. 'trends_score'), which would clobber the raw value.
    # 'sources' reflects what actually contributed (post coverage-gate); computed
    # here while the frame is still qid-indexed so it survives the later sort.
    for s in DYNAMIC_SOURCES:
        df[f"{s}_ratio"] = scores[s]
    df["sources"] = [
        "+".join(s for s in DYNAMIC_SOURCES if elig[s].iloc[i]) for i in range(len(df))
    ]

    # Attention composite over eligible dynamic sources (renormalised per brand),
    # with search weighted highest.
    df["attention"] = combine_sources(scores, elig, weights or SOURCE_WEIGHTS)
    # Breadth from Wikipedia sitelink count — a minor co-factor only.
    df["breadth"] = sqrt_ratio_to_top5(df["sitelinks"].astype(float).fillna(0.0))

    # Attention-dominant blend. A brand with no eligible dynamic source
    # (attention NaN) scores on its breadth component ALONE (still weighted at
    # BREADTH_WEIGHT) — it must never out-rank brands that have real attention
    # data just because it has many Wikipedia editions.
    df["raw"] = BREADTH_WEIGHT * df["breadth"] + ATTENTION_WEIGHT * df["attention"].fillna(0.0)

    df = df.sort_values("raw", ascending=False).reset_index()
    df["rank"] = df.index + 1
    benchmark = df["raw"].head(5).mean()
    df["interest_index"] = (df["raw"] / benchmark * 100).round(1)
    df["tier"] = df["interest_index"].map(tier_of)
    return df


def enrich_titles(df: pd.DataFrame, wd: WikidataClient) -> pd.DataFrame:
    """Add per-language article titles for the rows, batched 50 at a time."""
    qids = df["qid"].tolist()
    titles: dict[str, dict[str, str]] = {}
    for start in range(0, len(qids), 50):
        batch = qids[start : start + 50]
        entities = wd.entities(batch)
        for qid, ent in entities.items():
            sl = ent.get("sitelinks", {})
            titles[qid] = {
                lang: sl[f"{lang}wiki"]["title"] for lang in LANGUAGES if f"{lang}wiki" in sl
            }
    for lang in LANGUAGES:
        df[f"{lang}_title"] = df["qid"].map(lambda q: titles.get(q, {}).get(lang, ""))
    df["wikipedia_langs"] = df["qid"].map(
        lambda q: ",".join(l for l in LANGUAGES if titles.get(q, {}).get(l))
    )
    return df


def build_index(cache_only: bool = True, do_trends: bool = True, verbose: bool = True) -> pd.DataFrame:
    """End-to-end: universe -> signals (from cache) -> scored, ranked full pool."""
    window = trailing_12_month_window(date.today())
    if verbose:
        print(f"Interest run — trailing-12mo window {window[0]}..{window[1]}")

    sp = SparqlClient(CACHE / "sparql")
    items = fetch_universe(sp)
    sp.close()
    viable = [i for i in items if i.sitelinks > 0 and i.label]
    if verbose:
        print(f"  universe {len(items)}; viable {len(viable)}")

    wd = WikidataClient(CACHE / "wikidata")
    editions = wd.wikipedia_sitelinks([i.qid for i in viable])

    from .gdelt import GdeltClient
    from .reddit import RedditClient
    from .trends import TrendsClient
    pv = PageviewsClient(CACHE / "pageviews")
    gdelt = GdeltClient(CACHE / "gdelt")
    trends = TrendsClient(CACHE / "trends")
    reddit = RedditClient(CACHE / "reddit")
    signals = gather_signals(
        viable, editions, pv, gdelt, trends, window,
        reddit=reddit, cache_only=cache_only, do_trends=do_trends, verbose=verbose,
    )
    pv.close(); gdelt.close(); trends.close(); reddit.close()

    df = score_universe(signals)
    df["n_wikipedias"] = df["qid"].map(lambda q: len(editions.get(q, {})))
    df = enrich_titles(df, wd)
    wd.close()
    return df


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    df = build_index(cache_only=True, do_trends=True, verbose=True)

    top = df.head(TOP_N).copy()
    top["review_flag"] = [review_flag(b, d) for b, d in zip(top["brand"], top["description"])]

    full_cols = ["rank", "tier", "interest_index", "qid", "brand", "description",
                 "sitelinks", "pv_12mo", "reddit_vol", "gdelt_12mo", "trends_score",
                 "sources", "n_wikipedias", "en_title"]
    cols = ["rank", "tier", "interest_index", "qid", "brand", "description", "review_flag",
            "sitelinks", "pv_12mo", "reddit_vol", "gdelt_12mo", "trends_score",
            "breadth", "attention", "sources", "n_wikipedias", "wikipedia_langs",
            ] + [f"{lang}_title" for lang in LANGUAGES]

    df[full_cols].to_csv(OUTPUT / "index_full_ranked.csv", index=False, encoding="utf-8")
    top[cols].to_csv(OUTPUT / "index_500.csv", index=False, encoding="utf-8")

    counts = top["tier"].value_counts().reindex(["A", "B", "C"]).fillna(0).astype(int)
    src_counts = {s: int(top[f"elig_{s}"].sum()) for s in DYNAMIC_SOURCES}
    print()
    print(f"Wrote {OUTPUT / 'index_500.csv'} (top {TOP_N}) and index_full_ranked.csv ({len(df)})")
    print(f"  tiers: A={counts['A']}  B={counts['B']}  C={counts['C']}")
    print(f"  source eligibility in top {TOP_N}: {src_counts}")
    print("  top 10:")
    for _, r in top.head(10).iterrows():
        g = "" if pd.isna(r["gdelt_12mo"]) else f"{int(r['gdelt_12mo']):,}"
        print(f"    {r['rank']:>3} [{r['tier']}] {r['interest_index']:>5}  {r['brand'][:26]:<26} "
              f"pv={int(r['pv_12mo']):>9,} gdelt={g:<8} src={r['sources']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
