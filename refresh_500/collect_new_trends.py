"""Bridge-anchored Google Trends (web) + News levels for the roster-surgery ADDS.

Tokens are PINNED from Wikidata (P646 Freebase / P2671 Google-KG mids) so no
Google resolution calls are spent and ambiguous names (COS, Bally) use the right
entity. Method matches trends_gap_recover.py / collect_news_levels.py:
  adidas100 = brand_mean / bridge_mean * bridge_adidas100
  basket1000 = adidas100 * RESCALE   (web 22.85714, news 26.28149)
  NEWS trust gate: topic mid AND web basket1000 present.
Patient + cache-resumable: only sleeps when a batch is NOT already cached, so a
re-run after a 429 resumes free.
"""
import sys, csv, time, random, json
from pathlib import Path

ROOT = Path(r"C:\Users\aresi\Claude\code\brand-index")
sys.path.insert(0, str(ROOT / "src"))
from vgr_brand_index.trends import TrendsClient, TrendsUnavailable

CACHE = ROOT / "cache" / "trends"
WEB_RESCALE, NEWS_RESCALE = 22.85714, 26.28149

# (display name, qid, pinned topic token)  -- Polène has no KG mid -> keyword
BRANDS = [
    ("Jacquemus", "Q21030814", "/g/11ckqmr261"),
    ("De Beers", "Q471891", "/m/0f21v"),
    ("Nude Project", "Q124984211", "/g/11v6c4b_42"),
    ("Polène", "Q122055705", "Polène"),
    ("Fashion Nova", "Q65090803", "/g/11h02ckjsb"),
    ("COS", "Q60772401", "/g/121hf5f0"),
    ("Brunello Cucinelli", "Q3645582", "/m/0105n26h"),
    ("Bally", "Q688195", "/m/06k8vt"),
    ("Charles & Keith", "Q3878818", "/m/0bmk0d9"),
    ("Scotch & Soda", "Q17141914", "/m/0y65pf5"),
]
BRIDGE_MID   = ("/m/03wr6g", 12.36, 12.81)   # Giorgio Armani (web, news)
BRIDGE_SMALL = ("/m/05fnqj", 9.19, None)     # Swarovski (web floor-retry)
tok = {n: t for n, _, t in BRANDS}

def is_mid(t): return isinstance(t, str) and t.startswith(("/m/", "/g/"))

def fetch_patient(client, toks):
    """Cache-first; on a live miss, retry the batch a few times with long waits."""
    cf = client._cache_path(toks)
    if cf.exists():
        return json.loads(cf.read_text(encoding="utf-8")), True   # cached
    for attempt in range(4):
        try:
            return client._fetch_batch(toks, cache_only=False), False
        except TrendsUnavailable as e:
            wait = 90 * (attempt + 1) + random.random() * 30
            print(f"    429/again ({str(e)[:40]}); wait {wait:.0f}s", flush=True)
            time.sleep(wait)
    raise TrendsUnavailable("gave up after patient retries")

def bridged(client, names, bridge, adidas_field):
    btok, badi = bridge[0], bridge[adidas_field]
    out = {}
    for i in range(0, len(names), 4):
        chunk = names[i:i+4]
        toks = [btok] + [tok[n] for n in chunk]
        means, was_cached = fetch_patient(client, toks)
        bm = means.get(btok, 0.0)
        for n in chunk:
            m = means.get(tok[n], 0.0)
            out[n] = round(m / bm * badi, 3) if bm > 0 else 0.0
        print(f"    batch {chunk} bridge_mean={bm:.1f} -> "
              + ", ".join(f"{n}={out[n]}" for n in chunk), flush=True)
        if not was_cached:
            time.sleep(random.uniform(45, 75))
    return out

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cool = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    print(f"cooldown {cool}s before first live call...", flush=True)
    time.sleep(cool)
    web  = TrendsClient(CACHE)
    news = TrendsClient(CACHE, gprop="news")
    names = [n for n, _, _ in BRANDS]

    print("=== WEB ===", flush=True)
    web_adi = bridged(web, names, BRIDGE_MID, 1)
    floored = [n for n in names if web_adi.get(n, 0) <= 0.05]
    if floored:
        print("web floor-retry (small bridge):", floored, flush=True)
        retry = bridged(web, floored, BRIDGE_SMALL, 1)
        for n, v in retry.items():
            if v > web_adi.get(n, 0): web_adi[n] = v

    print("=== NEWS ===", flush=True)
    news_adi = bridged(news, names, BRIDGE_MID, 2)

    rows = []
    for name, qid, t in BRANDS:
        w_adi = web_adi.get(name, 0.0)
        w_basket = round(w_adi * WEB_RESCALE, 2) if w_adi > 0.05 else ""
        n_adi = news_adi.get(name, 0.0)
        trusted = 1 if (is_mid(t) and w_basket != "") else 0
        n_basket = round(n_adi * NEWS_RESCALE, 2) if (trusted and n_adi > 0.05) else ""
        rows.append({"qid": qid, "brand": name, "token": t,
                     "trends_level_adidas100": w_adi, "trends_level_basket1000": w_basket,
                     "news_level_adidas100": n_adi, "news_level_basket1000": n_basket,
                     "trusted": trusted})
        print(f"  {name:<20} web={w_basket!s:<9} news={n_basket!s:<9} trusted={trusted}", flush=True)
    out = ROOT / "refresh_500" / "new_brands_trends.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader(); wr.writerows(rows)
    print("wrote", out, flush=True)

if __name__ == "__main__":
    main()
