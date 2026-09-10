import csv, subprocess, sys, re, os, time, random

ROOT = r"C:\Users\aresi\Claude\code\brand-index"
SK = r"C:/Users/aresi/.claude/skills/gdelt-brand-news/scripts/gdelt_news.py"
SRC = os.path.join(ROOT, "output", "latest", "index_500.csv")
OUTDIR = os.path.join(ROOT, "refresh_500")
CSVDIR = os.path.join(OUTDIR, "gdelt_csv")
MASTER = os.path.join(OUTDIR, "gdelt_500.csv")
PROG = os.path.join(OUTDIR, "gdelt_campaign.log")

MAX_HOURS = 22          # hard stop so it can't run forever
BATCH_MIN, BATCH_MAX = 10, 20      # random set size
GAP_MIN, GAP_MAX = 30, 40          # random minutes between sets
deadline = time.time() + MAX_HOURS * 3600

# Strip corporate/legal suffixes+prefixes so GDELT gets the plain brand name.
# A full string like "The North Face, Inc." returns nothing on GDELT; "The North Face" works.
_SUF_RE = re.compile(
    r'[\s,]+(?:inc|incorporated|ltd|limited|llc|gmbh|b\.?v\.?|n\.?v\.?|s\.?a\.?|'
    r's\.?p\.?a\.?|se|plc|ag|co|corp|corporation|company|holdings?|group|'
    r'international|fashion\s+group|and\s+sons|bootmaker)\.?\s*$', re.I)

def clean_query(brand, qid):
    if qid == "Q849724":          # index row whose name field is a stray Q-id
        return "Brioni"
    q = brand.strip()
    for pre in ("Boutique ", "Cia. "):
        if q.lower().startswith(pre.lower()):
            q = q[len(pre):]
    prev = None
    while prev != q:              # iteratively peel nested suffixes ("... International GmbH")
        prev = q
        q = _SUF_RE.sub("", q).rstrip(" .,&")
    return q.strip() or brand

def parse(out):
    d = {"median": "", "mom": "", "yoy": "", "status": "ok"}
    m = re.search(r"median monthly coverage volume.*?:\s*([\d,]+)", out)
    if m: d["median"] = int(m.group(1).replace(",", ""))
    m = re.search(r"MoM:\s*([+-]?\d+)%\s+YoY:\s*([+-]?\d+)%", out)
    if m: d["mom"], d["yoy"] = m.group(1) + "%", m.group(2) + "%"
    if "throttl" in out.lower() or "kept failing" in out.lower():
        d["status"] = "throttled"
    elif d["median"] == "":
        d["status"] = "parse_fail"
    return d

def load_done():
    done = set()
    if os.path.exists(MASTER):
        with open(MASTER, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["status"] == "ok":
                    done.add(r["qid"])
    return done

def log(msg):
    stamp = time.strftime("%H:%M:%S")
    with open(PROG, "a", encoding="utf-8") as p:
        p.write(f"[{stamp}] {msg}\n")

with open(SRC, encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

newfile = not os.path.exists(MASTER)
mf = open(MASTER, "a", newline="", encoding="utf-8")
w = csv.writer(mf)
if newfile:
    w.writerow(["rank_seed","brand","qid","gdelt_median_vol","mom","yoy","status"])
    mf.flush()

done = load_done()
pending = [(i, r) for i, r in enumerate(rows, 1) if r["qid"] not in done]
log(f"CAMPAIGN START: 500 brands, {len(done)} already ok, {len(pending)} pending. "
    f"sets of {BATCH_MIN}-{BATCH_MAX}, gaps {GAP_MIN}-{GAP_MAX} min, max {MAX_HOURS}h.")

set_no = 0
idx = 0
while idx < len(pending) and time.time() < deadline:
    set_no += 1
    size = random.randint(BATCH_MIN, BATCH_MAX)
    batch = pending[idx:idx + size]
    idx += size
    ok = throt = other = 0
    for i, r in batch:
        brand, qid = r["brand"], r["qid"]
        query = clean_query(brand, qid)   # GDELT gets the cleaned name; row keeps the original brand
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", brand)[:40]
        outp = os.path.join(CSVDIR, f"{safe}_{qid}.csv")
        try:
            p = subprocess.run([sys.executable, SK, query, "--out", outp],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=150)
            d = parse(p.stdout + p.stderr)
        except subprocess.TimeoutExpired:
            d = {"median":"","mom":"","yoy":"","status":"timeout"}
        w.writerow([i, brand, qid, d["median"], d["mom"], d["yoy"], d["status"]])
        mf.flush()
        if d["status"] == "ok": ok += 1
        elif d["status"] == "throttled": throt += 1
        else: other += 1
        time.sleep(3 + random.random() * 4)   # small human-like jitter within a set
    log(f"set {set_no}: {len(batch)} brands -> ok={ok} throttled={throt} other={other} "
        f"(cumulative pending left {len(pending) - idx})")
    if idx < len(pending) and time.time() < deadline:
        gap = random.uniform(GAP_MIN, GAP_MAX) * 60
        log(f"sleeping {gap/60:.1f} min before next set")
        time.sleep(gap)

# final tally
done = load_done()
log(f"CAMPAIGN PASS END: {len(done)}/500 ok after {set_no} sets. "
    f"{'ALL DONE' if len(done) >= len([r for r in rows]) else 'resumable — re-run to continue remaining'}")
mf.close()
print(f"gdelt campaign pass end: {len(done)}/500 ok, {set_no} sets")
