"""Build the self-contained interactive dashboard (dashboard.html).

Mirrors the polyamide-index pattern: one HTML file with the content rendered
**server-side** (so it is fully readable even where scripts don't run — email,
static snapshots, GitHub Pages) and the VGR logo embedded as a base64 data URI,
so it needs no network or external assets. JavaScript only adds interactivity
(search / tier filter / column sort) on top of the already-rendered rows.

    uv run python -m vgr_brand_index.dashboard            # from the latest shot
    uv run python -m vgr_brand_index.dashboard --month 2026-08
"""

from __future__ import annotations

import argparse
import base64
import html
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import deltas as deltas_mod
from . import store
from .interest import OUTPUT, ROOT
from .report import month_label

TEMPLATE = ROOT / "dashboard_template.html"
LOGO = Path(__file__).resolve().parent / "assets" / "vgr-logo-black.png"

DECK = ("Who is winning attention in fashion — the top 500 brands on one scale, "
        "from free public sources, refreshed monthly.")


def logo_data_uri() -> str:
    if not LOGO.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(LOGO.read_bytes()).decode("ascii")


def _isna(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v))


def _fmt(v) -> str:
    return "—" if _isna(v) else f"{int(round(float(v))):,}"


def _sources_html(s: str) -> str:
    if not s:
        return "—"
    return " · ".join(f"<b>{html.escape(x)}</b>" for x in s.split("+"))


def _tiers_html(top: pd.DataFrame) -> str:
    counts = top["tier"].value_counts().to_dict()
    spec = [("a", "A", "A — elite", "≥ 66"), ("b", "B", "B — established", "33–65"),
            ("c", "C", "C — long tail", "< 33")]
    return "".join(
        f'<div class="tcard {cls}"><div class="n">{int(counts.get(t, 0))}</div>'
        f'<div class="l">{lab}</div><div class="rng">index {rng}</div></div>'
        for cls, t, lab, rng in spec
    )


def _chart_html(top: pd.DataFrame) -> str:
    lead = top.head(20)
    mx = float(lead["interest_index"].max()) or 1.0
    out = []
    for i, (_, r) in enumerate(lead.iterrows()):
        w = float(r["interest_index"]) / mx * 100
        out.append(
            f'<div class="bar {"lead" if i == 0 else ""}"><div class="nm">{html.escape(str(r["brand"]))}</div>'
            f'<div class="track"><div class="fill" style="width:{w:.1f}%"></div></div>'
            f'<div class="v">{float(r["interest_index"]):.0f}</div></div>'
        )
    return "".join(out)


def _movers_html(d: deltas_mod.Deltas) -> tuple[str, str, str]:
    if not d.has_prior:
        return (
            "Baseline month",
            "No prior month yet — movement appears next month.",
            '<div class="note">This is the first shot. Next month\'s dashboard shows who grew, '
            "who crossed A↔B↔C, and who entered or left the 500.</div>",
        )

    def bars(movers, cls):
        col = "#1a7a3a" if cls == "up" else "var(--red-dk)"
        out = []
        for m in movers:
            dv = m.index_delta or 0
            w = min(100, abs(dv) * 3)
            out.append(
                f'<div class="bar"><div class="nm">{html.escape(m.brand)}</div>'
                f'<div class="track"><div class="fill" style="width:{w:.0f}%;background:{col}"></div></div>'
                f'<div class="v {cls}">{"+" if dv > 0 else ""}{dv:.1f}</div></div>'
            )
        return "".join(out)

    body = bars(d.top_risers[:7], "up") + bars(d.top_fallers[:4], "down")
    return "Biggest movers", f"Change in interest index vs {month_label(d.prev_month)}", body


def _rows_html(top: pd.DataFrame) -> str:
    mx = float(top["interest_index"].max()) or 1.0
    out = []
    for _, r in top.iterrows():
        idx = float(r["interest_index"])
        pv, gd, tr = r.get("pv_12mo"), r.get("gdelt_12mo"), r.get("trends_score")
        brand = html.escape(str(r["brand"]))
        out.append(
            f'<tr data-brand="{html.escape(str(r["brand"]).lower(), quote=True)}" '
            f'data-tier="{r["tier"]}" data-rank="{int(r["rank"])}" data-index="{idx:.1f}" '
            f'data-pv="{"" if _isna(pv) else int(pv)}" data-gdelt="{"" if _isna(gd) else int(gd)}" '
            f'data-trends="{"" if _isna(tr) else round(float(tr), 1)}">'
            f'<td class="num">{int(r["rank"])}</td>'
            f'<td><a href="https://www.wikidata.org/wiki/{r["qid"]}" target="_blank" rel="noopener">{brand}</a></td>'
            f'<td><span class="badge {r["tier"]}">{r["tier"]}</span></td>'
            f'<td class="num"><div class="idxcell"><div class="mini"><i style="width:{idx / mx * 100:.0f}%"></i></div>'
            f'<span>{idx:.1f}</span></div></td>'
            f'<td class="src">{_sources_html(r.get("sources", "") or "")}</td>'
            f'<td class="num">{_fmt(pv)}</td>'
            f'<td class="num">{_fmt(gd)}</td>'
            f'<td class="num">{"—" if _isna(tr) else f"{float(tr):.0f}"}</td>'
            f"</tr>"
        )
    return "".join(out)


def build_html(top: pd.DataFrame, d: deltas_mod.Deltas, generated: str | None = None) -> str:
    generated = generated or datetime.now().strftime("%d %b %Y")
    n = len(top)
    mtitle, msub, mbody = _movers_html(d)
    repl = {
        "%%LOGO_DATAURI%%": logo_data_uri(),
        "%%DECK%%": html.escape(DECK),
        "%%META%%": f"<b>{month_label(d.month)}</b> · {n} brands · top-5 average = 100 · generated {generated}",
        "%%TIERS%%": _tiers_html(top),
        "%%CHARTSUB%%": f"Interest index, top 20 of {n}",
        "%%CHART%%": _chart_html(top),
        "%%MOVERSTITLE%%": mtitle,
        "%%MOVERSSUB%%": msub,
        "%%MOVERS%%": mbody,
        "%%ROWS%%": _rows_html(top),
        "%%N%%": str(n),
        "%%GEN%%": f"Monthly shot {d.month} · prior {d.prev_month or 'none (baseline)'}.",
    }
    out = TEMPLATE.read_text(encoding="utf-8")
    for k, v in repl.items():
        out = out.replace(k, v)
    return out


def write_dashboard(top: pd.DataFrame, d: deltas_mod.Deltas, month: str, outdir: Path = OUTPUT) -> Path:
    html_str = build_html(top, d)
    dest = outdir / month / "dashboard.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html_str, encoding="utf-8")
    (outdir / "dashboard.html").write_text(html_str, encoding="utf-8")  # latest pointer
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
