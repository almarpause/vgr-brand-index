"""Monthly assemble + report — the deliverable half of the pipeline.

Cache-first (it reads what the nightly fetches accumulated, never hammering the
APIs live): refresh the universe, score the composite index, drop flagged parent
groups and backfill to keep 500, write the dated shot + append to history,
compute month-over-month deltas, render the .docx report, and (unless suppressed)
email it.

    uv run python -m vgr_brand_index.run_monthly --dry-run   # build, no email
    uv run python -m vgr_brand_index.run_monthly             # build + email
"""

from __future__ import annotations

import argparse
from datetime import date

import pandas as pd

from . import deltas as deltas_mod
from . import report as report_mod
from . import store
from .interest import OUTPUT, TOP_N, build_index, review_flag


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def assemble(month: str) -> pd.DataFrame:
    """Score from cache, drop flagged groups, keep the top 500 with fresh ranks."""
    df = build_index(cache_only=True, do_trends=True, verbose=True)
    df["review_flag"] = [review_flag(b, d) for b, d in zip(df["brand"], df["description"].fillna(""))]
    kept = df[df["review_flag"] == ""].reset_index(drop=True)
    top = kept.head(TOP_N).copy().reset_index(drop=True)
    top["rank"] = top.index + 1
    return top


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Assemble the monthly shot and report.")
    ap.add_argument("--month", default=current_month(), help="YYYY-MM (default: this month)")
    ap.add_argument("--dry-run", action="store_true", help="build everything, send no email")
    ap.add_argument("--no-email", action="store_true", help="build + save, but do not email")
    args = ap.parse_args(argv)
    month = args.month

    print(f"=== VGR Brand Score — monthly assemble {month} ===")
    top = assemble(month)
    counts = top["tier"].value_counts().reindex(["A", "B", "C"]).fillna(0).astype(int)
    print(f"  kept {len(top)} brands (groups dropped) — A={counts['A']} B={counts['B']} C={counts['C']}")

    # snapshot + history
    dest = store.write_snapshot(top, month)
    hist = store.update_history(top, month)
    d = deltas_mod.compute(hist, month)
    print(f"  history months: {store.months_in_history()}; prior = {d.prev_month or 'none (baseline)'}")

    # report + dashboard
    docx = dest / f"VGR_Brand_Index_{month}.docx"
    report_mod.build_report(top, d, docx)
    from . import dashboard
    dash = dashboard.write_dashboard(top, d, month)
    print(f"  wrote shot -> {dest}")
    print(f"  wrote report -> {docx}")
    print(f"  wrote dashboard -> {dash}")

    # email
    if args.dry_run or args.no_email:
        print("  email: skipped")
        return 0
    try:
        from . import emailer
        rc = emailer.send_report(docx, top, d)
        print(f"  email: {'sent' if rc == 0 else 'not sent (rc %d)' % rc}")
        return rc
    except Exception as exc:  # never let email failure lose the built report
        print(f"  email: skipped ({exc})")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
