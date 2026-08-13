"""Interest scoring, indexing and A/B/C tiering — Phase 0 deliverable.

Pipeline:
  1. universe   — query the fashion/footwear/sportswear/luxury pool from Wikidata
  2. pageviews  — trailing-12-month English Wikipedia views per brand (attention)
  3. blend      — 50/50 of normalised log(sitelinks) and log(pageviews)
  4. index      — scale so the mean score of the top 5 brands = 100
  5. tier        — A >= 66, B 33-65, C < 33 on that top-5-anchored scale
  6. cut         — keep the top 500 by interest

Design choices, stated plainly:
  * The pageview signal is English Wikipedia only (the index backbone and the
    single most comparable global attention series). Cross-language breadth is
    already rewarded by the sitelink half of the blend, so French-only brands
    still earn interest. Multi-language pageview blending is a later refinement.
  * Never invent a figure: a brand with no English article gets 0 pageviews
    (a real 'no signal', not an estimate) and rides on its sitelink score.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .pageviews import PageviewsClient, trailing_12_month_window
from .universe import SparqlClient, UniverseItem, fetch_universe
from .wikidata import LANGUAGES, WikidataClient

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "cache"
OUTPUT = ROOT / "output"

TIER_A_MIN = 66.0   # interest index (top-5 avg = 100)
TIER_B_MIN = 33.0
TOP_N = 500


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


def fetch_pageviews(items: list[UniverseItem], pv: PageviewsClient, window, verbose=True) -> dict[str, int]:
    """Trailing-12-month English pageviews per brand, keyed on Q-ID."""
    out: dict[str, int] = {}
    en_items = [i for i in items if i.en_title]
    for n, item in enumerate(en_items, 1):
        out[item.qid] = pv.trailing_12mo_total(item.en_title, "en", window)
        if verbose and (n % 100 == 0 or n == len(en_items)):
            print(f"    pageviews {n}/{len(en_items)}")
    return out


def _sqrt_ratio_to_top5(x: pd.Series) -> pd.Series:
    """sqrt(value) expressed as a ratio to the mean of the signal's top 5.

    sqrt is the variance-stabilising transform for count data (pageviews and
    sitelinks are both counts): it tames the heavy tail without erasing the real
    concentration of attention the way log does. Dividing by the top-5 mean puts
    both signals on the same 'share of the elite' scale before they are blended.
    """
    t = np.sqrt(x.astype(float))
    top5_mean = t.sort_values(ascending=False).head(5).mean()
    return t / top5_mean if top5_mean else t * 0.0


def score_universe(items: list[UniverseItem], pv_by_qid: dict[str, int]) -> pd.DataFrame:
    """Blend, index to the top-5 average, tier. Returns the full ranked pool."""
    rows = [
        {
            "qid": i.qid,
            "brand": i.label,
            "description": i.description,
            "sitelinks": i.sitelinks,
            "pv_12mo": pv_by_qid.get(i.qid, 0),
            "en_title": i.en_title,
        }
        for i in items
        # viable index members must be reachable by at least one Wikipedia edition
        if i.sitelinks > 0 and i.label
    ]
    df = pd.DataFrame(rows)

    # 50/50 blend of the two sqrt-ratio-to-top-5 signals
    df["sl_ratio"] = _sqrt_ratio_to_top5(df["sitelinks"])
    df["pv_ratio"] = _sqrt_ratio_to_top5(df["pv_12mo"])
    df["raw"] = 0.5 * df["sl_ratio"] + 0.5 * df["pv_ratio"]

    df = df.sort_values("raw", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    # Interest index: scale so the mean raw score of the top 5 brands = 100
    benchmark = df["raw"].head(5).mean()
    df["interest_index"] = (df["raw"] / benchmark * 100).round(1)
    df["score"] = (df["raw"] * 100).round(2)
    df["tier"] = df["interest_index"].map(tier_of)
    return df


def enrich_titles(df: pd.DataFrame, wd: WikidataClient) -> pd.DataFrame:
    """Add per-language article titles for the (top-N) rows, batched 50 at a time."""
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


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    today = date.today()
    window = trailing_12_month_window(today)
    print(f"Interest run — trailing-12mo window {window[0]}..{window[1]}")

    sp = SparqlClient(CACHE / "sparql")
    print("Fetching universe from Wikidata...")
    items = fetch_universe(sp)
    sp.close()
    print(f"  {len(items)} distinct brands; {sum(1 for i in items if i.en_title)} with English article")

    pv = PageviewsClient(CACHE / "pageviews")
    print("Fetching trailing-12mo English pageviews...")
    pv_by_qid = fetch_pageviews(items, pv, window)
    pv.close()

    df = score_universe(items, pv_by_qid)
    print(f"  scored {len(df)} viable brands (>=1 sitelink)")

    top = df.head(TOP_N).copy()
    top["review_flag"] = [review_flag(b, d) for b, d in zip(top["brand"], top["description"])]

    wd = WikidataClient(CACHE / "wikidata")
    print(f"Fetching per-language titles for top {TOP_N}...")
    top = enrich_titles(top, wd)
    wd.close()

    # Full ranked pool for audit; the 500-brand index as the deliverable.
    cols = [
        "rank", "tier", "interest_index", "score", "qid", "brand", "description",
        "review_flag", "sitelinks", "pv_12mo", "wikipedia_langs",
    ] + [f"{lang}_title" for lang in LANGUAGES]
    full_cols = ["rank", "tier", "interest_index", "score", "qid", "brand",
                 "description", "sitelinks", "pv_12mo", "en_title"]

    df[full_cols].to_csv(OUTPUT / "index_full_ranked.csv", index=False, encoding="utf-8")
    top[cols].to_csv(OUTPUT / "index_500.csv", index=False, encoding="utf-8")

    counts = top["tier"].value_counts().reindex(["A", "B", "C"]).fillna(0).astype(int)
    flagged = top[top["review_flag"] != ""]
    print()
    print(f"Wrote {OUTPUT / 'index_500.csv'}  (top {TOP_N})")
    print(f"Wrote {OUTPUT / 'index_full_ranked.csv'}  ({len(df)} ranked)")
    print(f"  tiers within top {TOP_N}: A={counts['A']}  B={counts['B']}  C={counts['C']}")
    print(f"  cut line: rank {TOP_N} interest_index = {top['interest_index'].iloc[-1]}")
    print(f"  flagged as parent group (review): {len(flagged)}  ({', '.join(flagged['brand'].head(12))})")
    print("  top 10:")
    for _, r in top.head(10).iterrows():
        print(f"    {r['rank']:>3} [{r['tier']}] {r['interest_index']:>5}  {r['brand'][:32]:<32} sl={r['sitelinks']:>3} pv={r['pv_12mo']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
