"""Build the monthly VGR Brand Score report (.docx).

Renders the Economist-navy Word document with the vendored `economist_navy`
engine and an economist-chart-style figure. The executive summary is composed
from the computed deltas in the vgr-voice register — answer-first, specific
numbers, no invented figures, no filler vocabulary. A separate Claude pass can
later rewrite the prose in full five-moves voice; the facts do not change.

Everything is self-contained (engine + logo vendored under the package) so a
headless scheduled run has no dependency on the skills plugin.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from . import economist_navy as en  # noqa: E402
from .deltas import Deltas, Mover  # noqa: E402

ASSETS = Path(__file__).resolve().parent / "assets"
LOGO = ASSETS / "vgr-logo-black.png"

# economist-chart-style palette
RED, NAVY, STEEL = "#C0110A", "#10294B", "#8E9BAA"
DARK, PANEL, INK = "#3D4A5A", "#E8EDF2", "#0A0A0A"
_avail = {f.name for f in font_manager.fontManager.ttflist}
SERIF = next((f for f in ("Georgia", "DejaVu Serif", "Liberation Serif") if f in _avail), "serif")
SANS = next((f for f in ("Arial", "Liberation Sans", "DejaVu Sans") if f in _avail), "sans-serif")

MONTHS = ["", "January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

DISCLAIMER = (
    "This document is produced by VGR | Very Good Retail for information and discussion "
    "purposes only. It is not investment advice. All figures are drawn from free public "
    "sources (Wikipedia pageviews, GDELT, Google Trends, Wikidata), cited in the method note. "
    "VGR accepts no liability for decisions taken on the basis of this document."
)


def month_label(month: str) -> str:
    y, m = month.split("-")
    return f"{MONTHS[int(m)]} {y}"


def _fmt_delta(v: float | None) -> str:
    if v is None:
        return "new"
    if v > 0:
        return f"+{v:.1f}"
    return f"{v:.1f}"


# ---------------------------------------------------------------- chart --------

def build_chart(top: pd.DataFrame, deltas: Deltas, out_png: Path) -> Path:
    """A horizontal bar chart: the month's biggest movers if there is a prior
    month, else the current attention leaders."""
    if deltas.has_prior and deltas.top_risers:
        movers = deltas.top_risers[:10][::-1]
        labels = [m.brand for m in movers]
        values = [m.index_delta for m in movers]
        headline = f"{deltas.top_risers[0].brand} led the month's gains"
        subtitle = f"Largest rise in interest index, {month_label(deltas.month)} vs {month_label(deltas.prev_month)}"
        unit = "index points"
    else:
        lead = top.head(12).iloc[::-1]
        labels = lead["brand"].tolist()
        values = lead["interest_index"].tolist()
        headline = f"{top.iloc[0]['brand']} leads the VGR Brand Score"
        subtitle = f"Interest index, top-5 average = 100, {month_label(deltas.month)}"
        unit = "interest index"

    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=200)
    fig.subplots_adjust(left=0.30, right=0.965, top=0.74, bottom=0.12)
    fig.patch.set_facecolor("white")
    ax.set_facecolor(PANEL)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(DARK)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.xaxis.grid(True, color="white", lw=1.1, zorder=1)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)

    colors = [RED if i == len(values) - 1 else NAVY for i in range(len(values))]
    ax.barh(range(len(values)), values, color=colors, zorder=3, height=0.72)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontfamily=SANS, fontsize=9, color=INK)
    ax.tick_params(axis="x", labelsize=8, colors=DARK)
    for i, v in enumerate(values):
        ax.text(v + max(values) * 0.01, i, _fmt_delta(v) if deltas.has_prior else f"{v:.0f}",
                va="center", ha="left", fontsize=8, fontfamily=SANS, color=INK, zorder=4)

    fig.add_artist(plt.Line2D([0.045, 0.16], [0.955, 0.955], color=RED, lw=3.2))
    fig.text(0.045, 0.90, headline, fontsize=13.5, fontweight="bold", family=SERIF, color=INK, va="top")
    fig.text(0.045, 0.845, subtitle, fontsize=9.0, family=SANS, color=DARK, va="top")
    fig.text(0.045, 0.03, f"VGR Brand Score · {unit} · source: Wikipedia, GDELT, Google Trends",
             fontsize=7.4, family=SANS, color=STEEL, va="bottom")

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, facecolor="white")
    plt.close(fig)
    return out_png


# ------------------------------------------------------------- summary ---------

def compose_summary(top: pd.DataFrame, deltas: Deltas) -> tuple[str, list[str], list[str]]:
    """Return (ruling finding, paragraphs, what-to-watch) in vgr-voice register."""
    counts = top["tier"].value_counts()
    a, b, c = int(counts.get("A", 0)), int(counts.get("B", 0)), int(counts.get("C", 0))
    lead = top.iloc[0]

    if not deltas.has_prior:
        ruling = f"{lead['brand']} opens the index at {lead['interest_index']:.0f}."
        p1 = (
            f"{lead['brand']} sits at the top of the {len(top)} brands the VGR Brand Score tracks, "
            f"at {lead['interest_index']:.0f} on a scale where the top five brands average 100. "
            f"{top.iloc[1]['brand']} follows at {top.iloc[1]['interest_index']:.0f} and "
            f"{top.iloc[2]['brand']} at {top.iloc[2]['interest_index']:.0f}."
        )
        p2 = (
            f"The A tier holds {a} brands, the B tier {b}, and the long C tail {c} — a distribution "
            f"that reflects how concentrated fashion attention is: a small elite draws most of it. "
            f"This is the baseline. Next month's report reads movement against it."
        )
        watch = [
            f"Whether {lead['brand']} holds the top as GDELT and Trends signal accumulates.",
            "The first tier crossings once a full month of nightly signal is in.",
            "Any new entrant forcing a brand out of the 500.",
        ]
        return ruling, [p1, p2], watch

    w = deltas.winner
    grew = _fmt_delta(w.index_delta)
    riser = deltas.top_risers[0] if deltas.top_risers else None
    ruling = (
        f"{w.brand} holds the lead at {w.index:.0f} ({grew})"
        + (f"; {riser.brand} is the month's sharpest gain." if riser else ".")
    )
    p1 = (
        f"{w.brand} stays top of the index at {w.index:.0f}, {grew} on the month. "
        + (f"Behind it, {deltas.top_risers[0].brand} added {_fmt_delta(deltas.top_risers[0].index_delta)} "
           f"to {deltas.top_risers[0].index:.0f}"
           + (f", and {deltas.top_risers[1].brand} {_fmt_delta(deltas.top_risers[1].index_delta)} "
              f"to {deltas.top_risers[1].index:.0f}." if len(deltas.top_risers) > 1 else ".")
           if deltas.top_risers else "")
    )
    # top vs middle
    top_line = ", ".join(f"{m.brand} ({_fmt_delta(m.index_delta)})" for m in deltas.a_movers[:3]) or "little changed"
    mid_line = ", ".join(f"{m.brand} ({_fmt_delta(m.index_delta)})" for m in deltas.b_movers[:3]) or "little changed"
    p2 = (
        f"At the top, the A tier moved on {top_line}. In the middle, the B tier's largest shifts were "
        f"{mid_line}."
    )
    migr = []
    if deltas.entered_a:
        migr.append(f"{', '.join(m.brand for m in deltas.entered_a[:4])} crossed into the A tier")
    if deltas.left_a:
        migr.append(f"{', '.join(m.brand for m in deltas.left_a[:4])} dropped out of it")
    if deltas.entered_500:
        migr.append(f"{len(deltas.entered_500)} brand(s) entered the 500")
    if deltas.left_500:
        migr.append(f"{len(deltas.left_500)} fell out")
    p3 = ("This month " + "; ".join(migr) + ".") if migr else "Tier membership held steady this month."

    watch = [
        f"Whether {riser.brand}'s rise holds or reverses." if riser else "Whether the top order holds.",
        "The next A/B boundary crossing.",
        "Entrants climbing the C tail toward the 500 cut.",
    ]
    return ruling, [p1, p2, p3], watch


# --------------------------------------------------------------- build ---------

def build_report(top: pd.DataFrame, deltas: Deltas, out_path: Path,
                 chart_png: Path | None = None) -> Path:
    """Render the .docx and return its path."""
    ml = month_label(deltas.month)
    if chart_png is None:
        chart_png = out_path.parent / "chart-1.png"
    build_chart(top, deltas, chart_png)
    ruling, paragraphs, watch = compose_summary(top, deltas)

    doc = en.new_document("VGR · BRAND INDEX")

    # -- cover --
    if LOGO.exists():
        en.figure(doc, str(LOGO), width_in=0.6, space_after=4)
    en.cover_masthead(doc, "VGR · BRAND INDEX")
    en.h1(doc, "The VGR Brand Score", deck=f"Attention across {len(top)} fashion brands — {ml}")
    en.source_line(doc, f"Monthly shot · {ml} · top-5 average = 100")
    en.stripe_band(doc)
    en.h2(doc, ruling)
    en.body(doc, paragraphs[0], drop=True)
    en.callout(doc, "DISCLAIMER", [DISCLAIMER])
    en.source_line(doc, "Sources: Wikipedia pageviews (all languages), GDELT, Google Trends, Wikidata.")
    en.page_break(doc)

    # -- executive summary --
    en.kicker(doc, "// EXECUTIVE SUMMARY")
    en.h2(doc, ruling)
    for para in paragraphs:
        en.body(doc, para)
    en.callout(doc, "WHAT TO WATCH", watch)
    en.figure(doc, str(chart_png), width_in=6.0)

    # -- top of the index --
    en.h2(doc, "The top of the index")
    rows = []
    for _, r in top.head(12).iterrows():
        rows.append([str(int(r["rank"])), r["brand"], r["tier"],
                     f"{r['interest_index']:.0f}", r.get("sources", "") or "—"])
    en.ledger_table(
        doc, ["#", "Brand", "Tier", "Index", "Signals"], rows,
        widths=[760, 3800, 1000, 1300, 2200], right_cols=(3,),
        source="Interest index, top-5 average = 100.",
    )

    # -- movers --
    if deltas.has_prior and (deltas.top_risers or deltas.top_fallers):
        en.h2(doc, "Biggest movers")
        mrows = []
        for m in deltas.top_risers[:6]:
            mrows.append([m.brand, m.tier, f"{m.index:.0f}", _fmt_delta(m.index_delta),
                          f"{m.rank_delta:+d}" if m.rank_delta is not None else "—"])
        for m in deltas.top_fallers[:4]:
            mrows.append([m.brand, m.tier, f"{m.index:.0f}", _fmt_delta(m.index_delta),
                          f"{m.rank_delta:+d}" if m.rank_delta is not None else "—"])
        en.ledger_table(
            doc, ["Brand", "Tier", "Index", "Δ index", "Δ rank"], mrows,
            widths=[3560, 1000, 1300, 1600, 1600], right_cols=(2, 3, 4),
            source=f"Change vs {month_label(deltas.prev_month)}. Δ rank positive = climbed.",
        )

    # -- method --
    en.h2(doc, "Method")
    en.body(doc,
            "Interest blends Wikipedia sitelink breadth with an attention composite of all-language "
            "pageviews, GDELT news volume and Google Trends search interest. Each signal is "
            "square-root-scaled to its top-5 mean; the composite renormalises over the sources "
            "available for each brand. No figure is estimated — a source with no value for a brand "
            "is simply not counted.")
    en.colophon(doc, [
        ("VGR | Very Good Retail — Brand Score", "label"),
        (f"Monthly shot: {deltas.month}. Prior: {deltas.prev_month or 'none (baseline)'}.", "text"),
        ("Free public sources; every figure traceable to a source and a fetch timestamp.", "text"),
    ])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path
