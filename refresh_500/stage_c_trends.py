"""STAGE C - Trends for the new members + qmap hygiene.

Renames are cosmetic for Trends (lookup is by qid; existing tokens already
resolve to the correct brand entities), so nothing is re-queried for them.
Only work:
  1. qmap: map each new display name -> the verified brand token (by qid), so
     future live runs (run_monthly) resolve the renamed brand correctly.
     Also repairs the bad bare-word probe "On" -> the On-running-brand mid.
  2. Adidas (Q3895): level already known (anchor=100 -> basket 2285.74). Add row.
  3. Backfill (Gymshark, TK Maxx, Eddie Bauer): live Adidas-anchored Trends query
     via the upgraded resolver, converted to the basket-1000 scale. Staggered.
"""
import csv, json, sys, shutil
from pathlib import Path

ROOT = Path(r"C:\Users\aresi\Claude\code\brand-index")
sys.path.insert(0, str(ROOT / "src"))
from vgr_brand_index.trends import TrendsClient

GTR   = ROOT / "refresh_500" / "gtrends_web_500.csv"
SURG  = json.loads((ROOT / "refresh_500" / "roster_surgery.json").read_text(encoding="utf-8"))
BASE  = json.loads((ROOT / "refresh_500" / "baseline_basket.json").read_text(encoding="utf-8"))
RESCALE = BASE["rescale_factor"]            # adidas100 -> basket1000
CACHE = ROOT / "cache" / "trends"

rows = list(csv.DictReader(open(GTR, encoding="utf-8")))
cols = list(rows[0].keys())
by_qid = {r["qid"]: r for r in rows}
qm = json.loads((CACHE / "_query_map.json").read_text(encoding="utf-8"))

def is_mid(t): return isinstance(t, str) and t.startswith(("/m/", "/g/"))

# --- 1) qmap hygiene: new display name -> verified token by qid ------------------
fixed = 0
for qid, new_name in SURG["rename"].items():
    tok = (by_qid.get(qid) or {}).get("token")
    if is_mid(tok):
        if qm.get(new_name) != tok:
            qm[new_name] = tok; fixed += 1
# repair the bad bare-word "On" probe explicitly (On AG's running-brand mid)
on_tok = (by_qid.get("Q43452713") or {}).get("token")
if is_mid(on_tok):
    qm["On"] = on_tok
(CACHE / "_query_map.json").write_text(json.dumps(qm, ensure_ascii=False), encoding="utf-8")
print(f"qmap: aligned {fixed} renamed display names to verified tokens; On -> {qm.get('On')}")

# --- backup gtrends before appending -------------------------------------------
shutil.copy(GTR, str(GTR) + ".bak_stagec")

# --- 2) Adidas row --------------------------------------------------------------
if "Q3895" not in by_qid:
    by_qid["Q3895"] = {c: "" for c in cols}
    by_qid["Q3895"].update({
        "qid": "Q3895", "brand": "Adidas", "token": "/g/1ym_1qtkc",
        "trends_level_adidas100": "100.0", "pv_median": "", "search_mom": "",
        "suspect_inflated": "0", "trends_level_basket1000": f"{round(100.0*RESCALE,2)}",
    })
    print(f"Adidas row added: basket level {round(100.0*RESCALE,2)}")

# --- 3) backfill: live Trends (staggered by the client throttle) ----------------
client = TrendsClient(CACHE)
backfill = {b["qid"]: SURG["rename"].get(b["qid"], b["brand"])
            for b in SURG["backfill_pool_provisional"]}
todo = {q: n for q, n in backfill.items()
        if not (by_qid.get(q, {}).get("trends_level_basket1000") or "").strip()}
if todo:
    names = list(todo.values())
    print(f"querying Trends (Adidas-anchored) for backfill: {names}")
    levels = client.score_brands(["Adidas"] + names)      # adidas100 per name
    name2qid = {n: q for q, n in todo.items()}
    for name, lvl in levels.items():
        q = name2qid.get(name)
        if q is None:
            continue
        adidas100 = lvl if lvl is not None else 0.0
        basket = round(adidas100 * RESCALE, 2) if adidas100 and adidas100 > 0 else ""
        tok = client.resolve_query(name, cache_only=True) or ""
        if q not in by_qid:
            by_qid[q] = {c: "" for c in cols}
        by_qid[q].update({
            "qid": q, "brand": name, "token": tok,
            "trends_level_adidas100": f"{adidas100}" if adidas100 else "",
            "suspect_inflated": "0",
            "trends_level_basket1000": f"{basket}",
        })
        print(f"  {name:<14} adidas100={adidas100}  basket1000={basket}  token={tok}")

# --- write ----------------------------------------------------------------------
with open(GTR, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader(); w.writerows(by_qid.values())
print(f"wrote {GTR}  rows={len(by_qid)}")
