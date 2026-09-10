"""STAGE A - deterministic roster surgery -> refresh_500/roster_500_v2.csv

Applies refresh_500/roster_surgery.json to output/2026-09/index_500.csv:
  * remove 4 sub-brand/collab qids
  * rename ~26 corporate names -> consumer brand form (homogeneous)
  * add Adidas (Q3895, force-include; universe roots miss it)
  * backfill 3 next-ranked Wikidata brands (already have pageviews)
Result: exactly 500 rows, same 35 columns. Scores are recomputed later by
rebuild_refresh.py (reads pv from wiki_500, trends from gtrends_web_500).
"""
import csv, json, sys
from pathlib import Path

ROOT = Path(r"C:\Users\aresi\Claude\code\brand-index")
sys.path.insert(0, str(ROOT / "src"))
from vgr_brand_index.universe import SparqlClient, build_values_query, _row_to_item

SEPT = ROOT / "output" / "2026-09" / "index_500.csv"
CFG  = json.loads((ROOT / "refresh_500" / "roster_surgery.json").read_text(encoding="utf-8"))
OUT  = ROOT / "refresh_500" / "roster_500_v2.csv"

rows = list(csv.DictReader(open(SEPT, encoding="utf-8")))
cols = list(rows[0].keys())
by_qid = {r["qid"]: r for r in rows}

# 1) remove
for q in CFG["remove_qids"]:
    by_qid.pop(q, None)

# 2) rename display brand
for q, name in CFG["rename"].items():
    if q in by_qid:
        by_qid[q]["brand"] = name

# 3+4) fetch metadata for the new members (Adidas + backfill) from universe cache
new_qids = [a["qid"] for a in CFG["add"]] + [b["qid"] for b in CFG["backfill_pool_provisional"]]
cl = SparqlClient(ROOT / "cache" / "sparql")
meta = {}
for r in cl.query(build_values_query(new_qids)):
    q, it = _row_to_item(r)
    meta[q] = it

def blank_row():
    return {c: "" for c in cols}

def add_member(qid, brand, desc, sitelinks, en_title, nwiki):
    r = blank_row()
    r.update({"qid": qid, "brand": brand, "description": desc,
              "sitelinks": str(sitelinks), "en_title": en_title,
              "n_wikipedias": str(nwiki), "review_flag": ""})
    # numeric score cols recomputed downstream; leave scoring fields blank/0
    for c in ("pv_median","pv_recent","pv_12mo","reddit_vol","trends_score"):
        r[c] = ""
    by_qid[qid] = r

# Adidas (explicit config values, fall back to universe)
for a in CFG["add"]:
    it = meta.get(a["qid"])
    add_member(a["qid"], a["brand"], a.get("description") or (it.description if it else ""),
               a.get("sitelinks") or (it.sitelinks if it else 0),
               a.get("en_title") or (it.en_title if it else a["brand"]),
               a.get("n_wikipedias") or (it.sitelinks if it else 0))

# backfill (name from rename map if present, else universe label)
for b in CFG["backfill_pool_provisional"]:
    it = meta.get(b["qid"])
    name = CFG["rename"].get(b["qid"], b["brand"])
    add_member(b["qid"], name, it.description if it else "",
               it.sitelinks if it else 0, it.en_title if it else name,
               it.sitelinks if it else 0)

# ---- validate + write
final = list(by_qid.values())
assert len(final) == 500, f"expected 500, got {len(final)}"
assert not (set(CFG["remove_qids"]) & set(by_qid)), "a removed qid survived"
assert "Q3895" in by_qid, "Adidas missing"
assert len({r['qid'] for r in final}) == 500, "duplicate qids"

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(final)

print(f"wrote {OUT}  rows={len(final)}")
print("Adidas:", by_qid["Q3895"]["brand"], "sitelinks", by_qid["Q3895"]["sitelinks"])
print("backfill:", [by_qid[b['qid']]['brand'] for b in CFG['backfill_pool_provisional']])
print("sample renames:", by_qid["Q127962"]["brand"], "|", by_qid["Q43452713"]["brand"],
      "|", by_qid["Q152784"]["brand"], "|", by_qid["Q1095857"]["brand"])
