"""Collect Wikidata breadth + Wikipedia pageviews for the roster-surgery ADDS.

Same method as the rest of the index:
  sitelinks   = total Wikidata sitelink count (breadth input)
  n_wikipedias= number of Wikipedia language editions
  pv_median   = median monthly all-edition pageviews over the trailing-12 window
Writes refresh_500/new_brands_wiki.csv.
"""
import sys, json, statistics, urllib.request, urllib.parse
from pathlib import Path
from collections import defaultdict

ROOT = Path(r"C:\Users\aresi\Claude\code\brand-index")
sys.path.insert(0, str(ROOT / "src"))
from vgr_brand_index.pageviews import PageviewsClient, trailing_12_month_window
from vgr_brand_index.wikidata import wikipedia_edition, USER_AGENT

NEW = {
    # named additions
    "Q97394724": "Jacquemus",
    "Q471891":  "De Beers",
    "Q124984211": "Nude Project",
    "Q122055705": "Polène",
    # backfill from pool
    "Q65090803": "Fashion Nova",
    "Q60772401": "COS",
    "Q3645582":  "Brunello Cucinelli",
    "Q688195":   "Bally",
    "Q3878818":  "Charles & Keith",
    "Q17141914": "Scotch & Soda",
}

def entitydata(qid):
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return json.load(urllib.request.urlopen(req, timeout=30))["entities"][qid]

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    win = trailing_12_month_window()
    print("pageviews window:", win)
    pv = PageviewsClient(ROOT / "cache" / "pageviews")
    rows = []
    for qid, name in NEW.items():
        ent = entitydata(qid)
        sl = ent.get("sitelinks", {})
        total_sitelinks = len(sl)
        editions = {}
        for site, link in sl.items():
            lang = wikipedia_edition(site)
            if lang:
                editions[lang] = link.get("title", "")
        n_wiki = len(editions)
        en_label = ent.get("labels", {}).get("en", {}).get("value", name)
        en_desc = ent.get("descriptions", {}).get("en", {}).get("value", "")
        en_title = editions.get("en", en_label)
        # pageviews: sum across all editions per month, median
        monthly = defaultdict(int)
        for lang, title in editions.items():
            try:
                for ts, v in pv.fetch(title, lang, win[0], win[1], "monthly", cache_only=False):
                    monthly[ts[:7]] += v
            except Exception as e:
                print(f"    pv fail {lang}:{title} -> {str(e)[:60]}")
        series = [monthly[k] for k in sorted(monthly)]
        pv_median = int(statistics.median(series)) if series else 0
        pv_latest = series[-1] if series else 0
        rows.append({
            "qid": qid, "brand": name, "description": en_desc,
            "sitelinks": total_sitelinks, "en_title": en_title,
            "n_wikipedias": n_wiki, "pv_median": pv_median, "pv_latest": pv_latest,
            "months": len(series),
        })
        print(f"  {name:<20} sitelinks={total_sitelinks:>3} n_wiki={n_wiki:>3} "
              f"pv_median={pv_median:>8,} ({len(series)}mo)")
    import csv
    out = ROOT / "refresh_500" / "new_brands_wiki.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("wrote", out)

if __name__ == "__main__":
    main()
