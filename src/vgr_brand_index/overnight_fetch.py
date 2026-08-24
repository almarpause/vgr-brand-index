"""One-night staggered bulk fetch of every attention signal for the top brands.

Kicked off ~22:15, it works through the night with a hard stop at 09:00, so the
morning has a full multi-signal dataset. Everything is:
  * cache-first — anything already fetched is skipped, so it resumes cleanly;
  * error-tolerant — every fetch is wrapped, a failure logs and moves on, the
    run never crashes;
  * gently paced — each source keeps its own throttle, so nothing is hammered.

Order: Reddit (browser, ~1h) and Google Trends first (the signals we most need),
then GDELT news (the slow one) fills the rest of the night.

    uv run python -m vgr_brand_index.overnight_fetch [--top 600]
"""

from __future__ import annotations

import argparse
from datetime import datetime, time as dtime, timedelta

from .gdelt import GdeltClient
from .interest import CACHE
from .pageviews import PageviewsClient, trailing_12_month_window
from .reddit_browser import RedditBrowserClient
from .signals import gather_signals
from .trends import TrendsClient
from .universe import SparqlClient, fetch_universe
from .wikidata import WikidataClient

STOP_AT = dtime(9, 0)


def deadline() -> datetime:
    now = datetime.now()
    d = now.replace(hour=STOP_AT.hour, minute=STOP_AT.minute, second=0, microsecond=0)
    return d if now < d else d + timedelta(days=1)


def _top_labels(top_n: int) -> list[str]:
    window = trailing_12_month_window()
    sp = SparqlClient(CACHE / "sparql")
    items = fetch_universe(sp)
    sp.close()
    viable = [i for i in items if i.sitelinks > 0 and i.label]
    wd = WikidataClient(CACHE / "wikidata")
    editions = wd.wikipedia_sitelinks([i.qid for i in viable])
    wd.close()
    pv = PageviewsClient(CACHE / "pageviews")
    df = gather_signals(viable, editions, pv, None, None, window, cache_only=True, do_trends=False)
    pv.close()
    return df.sort_values("pv_median", ascending=False)["brand"].tolist()[:top_n]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Overnight staggered fetch of all signals.")
    ap.add_argument("--top", type=int, default=600, help="how many top brands (by pageviews) to fetch")
    ap.add_argument("--hours", type=float, default=None,
                    help="run for this many hours from now instead of stopping at 09:00")
    args = ap.parse_args(argv)
    end = (datetime.now() + timedelta(hours=args.hours)) if args.hours else deadline()
    print(f"=== overnight fetch — until {end:%Y-%m-%d %H:%M} ===", flush=True)

    labels = _top_labels(args.top)
    print(f"top {len(labels)} brands by pageviews queued", flush=True)

    def timed_out() -> bool:
        return datetime.now() >= end

    # -- Reddit (browser) --
    print("[reddit] browser buzz...", flush=True)
    rb = RedditBrowserClient()
    got = 0
    try:
        for i, b in enumerate(labels, 1):
            if timed_out():
                break
            try:
                v = rb.fetch(b)
                got += 1 if v is not None else 0
            except Exception as exc:
                print(f"    [reddit] skip {b!r}: {str(exc)[:60]}", flush=True)
            if i % 25 == 0:
                print(f"    [reddit] {i}/{len(labels)} got={got}", flush=True)
    finally:
        rb.close()
    print(f"[reddit] done — {got} fetched", flush=True)

    # -- Google Trends (best-effort; may be blocked) --
    print("[trends] search interest (best-effort)...", flush=True)
    tc = TrendsClient(CACHE / "trends", min_interval=8.0, jitter=5.0)
    try:
        if not timed_out():
            scores = tc.score_brands(labels, cache_only=False)
            print(f"[trends] {sum(1 for v in scores.values() if v is not None)} scored", flush=True)
    except Exception as exc:
        print(f"[trends] gave up: {str(exc)[:80]}", flush=True)
    finally:
        tc.close()

    # -- GDELT news (the slow bulk; fills the rest of the night) --
    print("[gdelt] news volume...", flush=True)
    window = trailing_12_month_window()
    gc = GdeltClient(CACHE / "gdelt")
    got = 0
    try:
        for i, b in enumerate(labels, 1):
            if timed_out():
                print("    [gdelt] deadline reached", flush=True)
                break
            try:
                v = gc.monthly_total(b, window[0], window[1])
                got += 1 if v is not None else 0
            except Exception as exc:
                print(f"    [gdelt] skip {b!r}: {str(exc)[:60]}", flush=True)
            if i % 20 == 0:
                print(f"    [gdelt] {i}/{len(labels)} got={got}", flush=True)
    finally:
        gc.close()
    print(f"[gdelt] done — {got} fetched", flush=True)

    print(f"=== overnight fetch finished at {datetime.now():%H:%M} ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
