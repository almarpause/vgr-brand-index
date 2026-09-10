import subprocess, sys, time, csv, os

ROOT = r"C:\Users\aresi\Claude\code\brand-index"
CAMPAIGN = os.path.join(ROOT, "schedule", "gdelt", "gdelt_campaign.py")
GDELT_CSV = os.path.join(ROOT, "refresh_500", "gdelt_500.csv")
LOG = os.path.join(ROOT, "refresh_500", "gdelt_loop.log")

MAX_HOURS = 12            # bounded window for the scheduled Saturday run
COOLDOWN_MIN = 15         # rest between passes to let GDELT's throttle relax
ZERO_STREAK_STOP = 3      # stop after this many consecutive zero-gain passes

def ok_count():
    with open(GDELT_CSV, encoding="utf-8") as f:
        return len(set(r["qid"] for r in csv.DictReader(f) if r["status"] == "ok"))

def log(msg):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

deadline = time.time() + MAX_HOURS * 3600
zero_streak = 0
p = 0
log(f"SCHEDULED GDELT LOOP START at {ok_count()} ok; max {MAX_HOURS}h, stop after {ZERO_STREAK_STOP} zero-gain passes")
while time.time() < deadline:
    p += 1
    before = ok_count()
    subprocess.run([sys.executable, CAMPAIGN], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    after = ok_count()
    gain = after - before
    log(f"pass {p}: {before} -> {after}  (+{gain})")
    if gain == 0:
        zero_streak += 1
        if zero_streak >= ZERO_STREAK_STOP:
            log(f"CONVERGED: {zero_streak} consecutive zero-gain passes; stopping at {after}")
            break
    else:
        zero_streak = 0
    if time.time() < deadline:
        time.sleep(COOLDOWN_MIN * 60)

log(f"SCHEDULED GDELT LOOP END at {ok_count()} ok after {p} passes")
