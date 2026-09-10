"""Apply roster surgery and re-score.

  1. Drop the 10 non-fashion / out-of-scope removals.
  2. Add the 10 collected additions (new_brands_wiki.csv + new_brands_trends.csv).
  3. Re-score the 500 with the exact refresh engine (rebuild_roster.score).
  4. Back up + overwrite index_500_refreshed.csv; report the changes.
"""
import sys
from pathlib import Path
import pandas as pd, numpy as np

ROOT = Path(r"C:\Users\aresi\Claude\code\brand-index")
sys.path.insert(0, str(ROOT / "refresh_500"))
from rebuild_roster import score

R = ROOT / "refresh_500"
CSV = R / "index_500_refreshed.csv"

REMOVE = {
    "Q3974532": "Storm Management", "Q877571": "Blizzard Ski", "Q1360940": "Orbea",
    "Q19903561": "Polygon Bikes", "Q47545942": "Quooker", "Q272361": "Çalık Holding",
    "Q86327186": "GHOST-Bikes", "Q7642242": "Super Champion", "Q131445771": "Rapha",
    "Q3401000": "Nalini",
}

def num(x):
    try:
        f = float(x)
        return f if not np.isnan(f) else None
    except (TypeError, ValueError):
        return None

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    # Idempotent: always rebuild from the pre-surgery baseline, so re-running
    # (e.g. once Trends/News finally collects) re-does the surgery cleanly.
    bak = CSV.with_suffix(".csv.bak_surgery")
    src = bak if bak.exists() else CSV
    if not bak.exists():
        pd.read_csv(CSV).to_csv(bak, index=False)
        print(f"backup -> {bak.name}")
    df = pd.read_csv(src)
    cols = list(df.columns)
    assert len(df) == 500, len(df)

    # 1) remove ------------------------------------------------------------------
    present = [q for q in REMOVE if q in set(df["qid"])]
    assert len(present) == 10, f"only {len(present)} removals found: {present}"
    df = df[~df["qid"].isin(REMOVE)].copy()
    print(f"removed {len(present)} -> {len(df)} rows")

    # 2) build new rows ----------------------------------------------------------
    wiki = pd.read_csv(R / "new_brands_wiki.csv").set_index("qid")
    trf = R / "new_brands_trends.csv"
    if trf.exists():
        tr = pd.read_csv(trf).set_index("qid")
        print(f"trends file: {len(tr)} rows with Trends/News levels")
    else:
        tr = pd.DataFrame().set_index(pd.Index([], name="qid"))
        print("trends file MISSING -> new brands score on pageviews + breadth only")
    new_rows = []
    for qid in wiki.index:
        w = wiki.loc[qid]
        t = tr.loc[qid] if qid in tr.index else None
        trends_score = num(t["trends_level_basket1000"]) if t is not None else None
        news_score = num(t["news_level_basket1000"]) if t is not None else None
        pv_median = num(w["pv_median"]) or 0.0
        row = {c: np.nan for c in cols}
        row.update({
            "qid": qid, "brand": w["brand"], "description": w["description"],
            "sitelinks": float(w["sitelinks"]), "en_title": w["en_title"],
            "n_wikipedias": int(w["n_wikipedias"]), "review_flag": np.nan,
            "pv_median": pv_median,
            "trends_score": trends_score if trends_score else np.nan,
            "news_score": news_score if news_score else np.nan,
            "wiki_latest": num(w.get("pv_latest")),
            "elig_pv": pv_median > 0,
            "elig_trends": bool(trends_score and trends_score > 0),
            "elig_news": bool(news_score and news_score > 0),
        })
        new_rows.append(row)
    add = pd.DataFrame(new_rows)
    print(f"adding {len(add)} rows")
    df = pd.concat([df, add], ignore_index=True)
    assert len(df) == 500, len(df)

    # 3) re-score ----------------------------------------------------------------
    scored = score(df)[cols]

    # 4) validate ----------------------------------------------------------------
    old = pd.read_csv(src).set_index("qid")
    basket = ["Nike", "Adidas", "Zara", "H&M", "Hermès", "Louis Vuitton", "Gucci", "Uniqlo"]
    print("\ntop-8 basket interest_index (must be unchanged):")
    for b in basket:
        o = old[old["brand"] == b]["interest_index"]
        n = scored[scored["brand"] == b]["interest_index"]
        if len(o) and len(n):
            print(f"  {b:<16} old={o.iloc[0]:>6}  new={n.iloc[0]:>6}  {'OK' if abs(o.iloc[0]-n.iloc[0])<0.05 else 'CHANGED'}")
    tiers = scored["tier"].value_counts().to_dict()
    print(f"\ntiers: {tiers}  total={len(scored)}")
    print("\nNEW brands placement:")
    for qid in wiki.index:
        r = scored[scored["qid"] == qid].iloc[0]
        print(f"  rank {int(r['rank']):>3}  {r['brand']:<20} interest={r['interest_index']:>6} "
              f"tier={r['tier']} sources={r['sources']} pv={num(r['pv_median'])}")

    # 5) write -------------------------------------------------------------------
    scored.to_csv(CSV, index=False)
    print(f"wrote {CSV.name}  ({len(scored)} rows)")

if __name__ == "__main__":
    main()
