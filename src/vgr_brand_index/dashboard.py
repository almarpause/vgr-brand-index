"""Build the self-contained interactive dashboard (dashboard.html).

Mirrors the polyamide-index pattern: one HTML file with the data inlined and the
VGR logo embedded as a base64 data URI, so it opens by double-click, travels as
an email attachment, and needs no network or external assets. Economist chart
grammar, VGR styling.

    uv run python -m vgr_brand_index.dashboard            # from the latest shot
    uv run python -m vgr_brand_index.dashboard --month 2026-08
"""

from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import deltas as deltas_mod
from . import store
from .interest import OUTPUT, ROOT
from .report import month_label

TEMPLATE = ROOT / "dashboard_template.html"
LOGO = Path(__file__).resolve().parent / "assets" / "vgr-logo-black.png"


def logo_data_uri() -> str:
    if not LOGO.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(LOGO.read_bytes()).decode("ascii")


def _num(v):
    """None for missing, else a plain python number (JSON-safe, no NaN)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return float(v) if isinstance(v, float) else int(v)


def build_payload(top: pd.DataFrame, d: deltas_mod.Deltas, generated: str) -> dict:
    tiers = top["tier"].value_counts().to_dict()
    brands = [
        {
            "rank": int(r["rank"]),
            "brand": r["brand"],
            "tier": r["tier"],
            "index": round(float(r["interest_index"]), 1),
            "sources": r.get("sources", "") or "",
            "qid": r["qid"],
            "pv": _num(r.get("pv_12mo")),
            "gdelt": _num(r.get("gdelt_12mo")),
            "trends": _num(r.get("trends_score")),
        }
        for _, r in top.iterrows()
    ]
    mv = {
        "prev_month": d.prev_month,
        "prev_label": month_label(d.prev_month) if d.prev_month else None,
        "risers": [{"brand": m.brand, "delta": m.index_delta} for m in d.top_risers],
        "fallers": [{"brand": m.brand, "delta": m.index_delta} for m in d.top_fallers],
    }
    return {
        "meta": {
            "title": "VGR Brand Index",
            "deck": "Who is winning attention in fashion — 500 brands on one scale, "
                    "from free public sources, refreshed monthly.",
            "month": d.month,
            "month_label": month_label(d.month),
            "prev_month": d.prev_month,
            "generated": generated,
            "n": len(top),
            "tiers": {t: int(tiers.get(t, 0)) for t in ("A", "B", "C")},
        },
        "brands": brands,
        "movers": mv,
    }


def build_html(top: pd.DataFrame, d: deltas_mod.Deltas, generated: str | None = None) -> str:
    generated = generated or datetime.now().strftime("%d %b %Y")
    payload = json.dumps(build_payload(top, d, generated), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    return html.replace("%%DATA%%", payload).replace("%%LOGO_DATAURI%%", logo_data_uri())


def write_dashboard(top: pd.DataFrame, d: deltas_mod.Deltas, month: str, outdir: Path = OUTPUT) -> Path:
    html = build_html(top, d)
    dest = outdir / month / "dashboard.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")
    (outdir / "dashboard.html").write_text(html, encoding="utf-8")  # latest pointer
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the interactive dashboard from a shot.")
    ap.add_argument("--month", default=None, help="YYYY-MM (default: latest in history)")
    args = ap.parse_args(argv)

    hist = store.load_history()
    if hist.empty:
        raise SystemExit("no history yet — run vgr-run-monthly first")
    month = args.month or store.months_in_history()[-1]
    csv = OUTPUT / month / "index_500.csv"
    if not csv.exists():
        raise SystemExit(f"no shot at {csv} — run vgr-run-monthly --month {month}")
    top = pd.read_csv(csv)
    d = deltas_mod.compute(hist, month)
    dest = write_dashboard(top, d, month)
    print(f"[dashboard] wrote {dest} ({dest.stat().st_size:,} bytes) and {OUTPUT / 'dashboard.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
