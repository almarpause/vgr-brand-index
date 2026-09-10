"""Staggered gap-recovery for the comparable Google Trends level (Adidas=100).

Recovers two clean categories from refresh_500/trends_gap_plan.csv:
  * crushed (49): valid token, but floored to <0.5 against the huge Adidas anchor.
      Re-query each against a mid-size BRIDGE brand (known Adidas-level), so the
      weekly integers are large enough to carry signal, then rescale to Adidas=100:
          adidas_level = brand_mean_in_batch / bridge_mean_in_batch * bridge_adidas_level
  * missing (38): no entity resolved yet. Resolve via suggestions, query against the
      Adidas anchor; if it floors, retry against the bridge.

The 27 'suspect' (wrong-entity) rows are DEFERRED — they need entity judgment, not a
query, and are left quarantined.

Staggered: TrendsClient throttles 4-7s/call; we add a jittered pause between batches
and a longer rest every REST_EVERY batches so we don't re-trip Google's 429. Batch
fetches are cached under cache/trends, so the run is fully resumable.
"""
import csv, json, sys, time, random
from pathlib import Path

ROOT = Path(r"C:\Users\aresi\Claude\code\brand-index")
sys.path.insert(0, str(ROOT / "src"))
from vgr_brand_index.trends import TrendsClient, clean_term

CACHE = ROOT / "cache" / "trends"
GTR   = ROOT / "refresh_500" / "gtrends_web_500.csv"
PLAN  = ROOT / "refresh_500" / "trends_gap_plan.csv"
OUT   = ROOT / "refresh_500" / "trends_gap_recovered.csv"
LOG   = ROOT / "refresh_500" / "trends_gap.log"

BATCH = 4
PAUSE_MIN, PAUSE_MAX = 8, 16      # jittered seconds between batches
REST_EVERY, REST_SEC = 8, 90      # longer rest to keep under the 429 radar
CRUSH_FLOOR = 0.5                  # below this = still floored

def num(s):
    try: return float(s)
    except (TypeError, ValueError): return None

def log(msg):
    stamp = time.strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

client = TrendsClient(CACHE)
ADIDAS = client.resolve_query("Adidas", cache_only=True) or "/g/1ym_1qtkc"

# --- known-good Adidas-levels (for bridge pick + missing plausibility) ----------
good = {}
for r in csv.DictReader(open(GTR, encoding="utf-8")):
    lvl = num(r["trends_level_adidas100"])
    if lvl and 0.5 <= lvl <= 140 and r.get("suspect_inflated") != "1":
        good[r["brand"]] = lvl

# Bridge = a brand with a solid mid level (~8-14) and a resolvable token.
bridge_name = bridge_tok = None; bridge_lvl = None
for name, lvl in sorted(good.items(), key=lambda kv: abs(kv[1] - 11)):
    tok = client.resolve_query(name, cache_only=True)
    if tok:
        bridge_name, bridge_tok, bridge_lvl = name, tok, lvl
        break
if not bridge_tok:
    log("FATAL: no bridge anchor found"); sys.exit(1)
log(f"bridge anchor = {bridge_name!r} token={bridge_tok} adidas_level={bridge_lvl:.2f}")

# --- load plan ------------------------------------------------------------------
plan = list(csv.DictReader(open(PLAN, encoding="utf-8")))
crushed = [r for r in plan if r["category"] == "crushed"]
missing = [r for r in plan if r["category"] == "missing"]
log(f"plan: crushed={len(crushed)} missing={len(missing)} (suspect deferred)")

# resume: skip qids already recovered
done = set()
if OUT.exists():
    done = {r["qid"] for r in csv.DictReader(open(OUT, encoding="utf-8"))}
    log(f"resume: {len(done)} already recovered")

newfile = not OUT.exists()
of = open(OUT, "a", newline="", encoding="utf-8")
w = csv.writer(of)
if newfile:
    w.writerow(["qid","brand","token","category","batch_anchor",
                "anchor_adidas_level","brand_mean","anchor_mean","recovered_level_adidas100"])
    of.flush()

def fetch(tokens):
    return client._fetch_batch(tokens, cache_only=False)

n_batch = 0
def rest():
    global n_batch
    n_batch += 1
    if n_batch % REST_EVERY == 0:
        log(f"  rest {REST_SEC}s after {n_batch} batches")
        time.sleep(REST_SEC)
    else:
        time.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))

# --- crushed: bridge-anchored ---------------------------------------------------
recov = 0
todo = [r for r in crushed if r["qid"] not in done]
for i in range(0, len(todo), BATCH):
    batch = todo[i:i+BATCH]
    toks, tokof = [bridge_tok], {}
    for r in batch:
        t = r["token"] or client.resolve_query(r["brand"])
        if t: toks.append(t); tokof[r["qid"]] = t
    if len(toks) < 2:
        continue
    try:
        means = fetch(toks)
    except Exception as e:
        log(f"  crushed batch fail: {str(e)[:80]}"); rest(); continue
    am = means.get(bridge_tok, 0.0)
    for r in batch:
        t = tokof.get(r["qid"]);  bm = means.get(t, 0.0) if t else 0.0
        lvl = round(bm / am * bridge_lvl, 3) if am > 0 else 0.0
        w.writerow([r["qid"], r["brand"], t or "", "crushed", bridge_name,
                    f"{bridge_lvl:.2f}", f"{bm:.2f}", f"{am:.2f}", lvl]); of.flush()
        recov += 1
    log(f"crushed {i//BATCH+1}: {len(batch)} brands (anchor_mean={am:.1f})")
    rest()

# --- missing: resolve then Adidas-anchored (bridge retry if floored) ------------
todo = [r for r in missing if r["qid"] not in done]
for i in range(0, len(todo), BATCH):
    batch = todo[i:i+BATCH]
    toks, tokof = [ADIDAS], {}
    for r in batch:
        t = client.resolve_query(r["brand"])          # live suggestions lookup
        if t: toks.append(t); tokof[r["qid"]] = t
    if len(toks) < 2:
        continue
    try:
        means = fetch(toks)
    except Exception as e:
        log(f"  missing batch fail: {str(e)[:80]}"); rest(); continue
    am = means.get(ADIDAS, 0.0)
    floored = []
    for r in batch:
        t = tokof.get(r["qid"]); bm = means.get(t, 0.0) if t else 0.0
        lvl = round(bm / am * 100.0, 3) if am > 0 else 0.0
        if 0 <= lvl < CRUSH_FLOOR and t:
            floored.append((r, t))
        else:
            w.writerow([r["qid"], r["brand"], t or "", "missing", "Adidas",
                        "100.00", f"{bm:.2f}", f"{am:.2f}", lvl]); of.flush()
            recov += 1
    log(f"missing {i//BATCH+1}: {len(batch)-len(floored)} placed, {len(floored)} floored")
    rest()
    # bridge retry for floored missing
    if floored:
        toks = [bridge_tok] + [t for _, t in floored]
        try:
            means = fetch(toks); am = means.get(bridge_tok, 0.0)
            for r, t in floored:
                bm = means.get(t, 0.0)
                lvl = round(bm / am * bridge_lvl, 3) if am > 0 else 0.0
                w.writerow([r["qid"], r["brand"], t, "missing", bridge_name,
                            f"{bridge_lvl:.2f}", f"{bm:.2f}", f"{am:.2f}", lvl]); of.flush()
                recov += 1
            log(f"  missing bridge-retry: {len(floored)} placed")
        except Exception as e:
            log(f"  missing bridge-retry fail: {str(e)[:80]}")
        rest()

of.close()
log(f"DONE: recovered {recov} rows -> {OUT}")
print(f"recovered {recov}")
