"""Build the VGR Brand Index website payload from the refreshed collection.

Produces two files at the project root (mirrors the VGR 40 `dashboard.py`):

  Brand_Index_Dashboard.html   the ready-made dashboard (self-contained HTML)
  brand_index_data.json        a CORS-open data feed (index + all 500 brands),
                               so a native site component can render it live.

Both are rebuilt DETERMINISTICALLY from the committed CSVs in refresh_500/ —
this script collects no live data, so it runs safely in CI (GitHub Actions).
Data refresh stays local: re-run the collection, commit the new CSVs, push,
and the Action republishes the site. See WEB_DEPLOY.md.

Table layout (grouped "subsets", VGR prominent, per-source detail greyed):
  Position | Brand | Tier
  -- VGR ------------  VGR interest | % vs last month
  -- google search --  g search idx | % vs last month
  -- google news ----  g news idx   | % vs last month
  -- wikipedia ------  wikipedia    | % vs last month

Score = Attention (Google search 50% + Google news 30% + Wikipedia pageviews
20%, renormalised per brand over the sources a brand actually has) + Breadth.
Both Google levels are anchor-chained to Adidas from cached pytrends batches and
referenced to the frozen 8-brand basket (average = 1,000). The VGR "% vs last
month" is a true like-for-like delta vs a reconstructed August cross-section
scored by the identical engine (see reconstruct_aug_vgr).
"""
import base64, csv, html, json, re, sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
REFRESH = ROOT / "refresh_500"
TEMPLATE = ROOT / "dashboard_template.html"
LOGO = ROOT / "src" / "vgr_brand_index" / "assets" / "vgr-logo-black.png"
OUT_HTML = ROOT / "Brand_Index_Dashboard.html"
OUT_JSON = ROOT / "brand_index_data.json"

MONTH = "September 2026"
DECK = ("Who is winning attention in fashion — the top 500 brands on one scale, "
        "from free public sources. September 2026, refreshed.")


def logo_uri():
    return "data:image/png;base64," + base64.b64encode(LOGO.read_bytes()).decode("ascii") if LOGO.exists() else ""


def esc(s):
    return html.escape(str(s))


def pctnum(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).strip()
    if not s or s.lower() in ("n/a", "na", "nan"):
        return None
    m = re.search(r"([+-]?\d[\d,]*)", s)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    if ">" in s or "breakout" in s.lower():
        v = max(v, 5000.0)
    return v


def _breakout(raw):
    raws = "" if (raw is None or (isinstance(raw, float) and pd.isna(raw))) else str(raw).strip()
    return ">" in raws or "breakout" in raws.lower()


def mom_badge_grey(raw):
    """De-emphasised momentum cell for the source-detail subsets."""
    v = pctnum(raw)
    if v is None:
        return '<span style="color:#c2c6cd">—</span>', ""
    arrow = "▲" if v > 0 else ("▼" if v < 0 else "•")
    label = "breakout" if _breakout(raw) else f"{v:+.0f}%"
    return (f'<span style="color:#9aa0aa;font-variant-numeric:tabular-nums;white-space:nowrap">'
            f'{arrow}&nbsp;{esc(label)}</span>', f"{v:.0f}")


def fmt_int(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '<span style="color:#c2c6cd">—</span>', ""
    return f"{int(round(float(v))):,}", str(int(round(float(v))))


def fmt_level(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '<span style="color:#c2c6cd">—</span>', ""
    v = float(v)
    if v <= 0:
        return '<span style="color:#c2c6cd">—</span>', ""
    txt = f"{v:,.0f}" if v >= 10 else f"{v:.1f}"
    return (f'<span style="font-variant-numeric:tabular-nums">{txt}</span>', f"{v:.2f}")


df = pd.read_csv(REFRESH / "index_500_refreshed.csv")

# Repair any brand whose display label failed to resolve during collection and
# fell back to a raw Wikidata id (e.g. "Q849724"). Use the English Wikipedia
# title, stripped of a trailing disambiguator, so this self-heals each refresh.
def _repair_label(row):
    b = str(row["brand"]).strip()
    if re.match(r"^Q\d+$", b):
        t = str(row.get("en_title") or "").strip()
        t = re.sub(r"\s*\((?:brand|company|clothing|label|fashion house|retailer|"
                   r"clothing brand|clothing company)\)\s*$", "", t, flags=re.I)
        return t or b
    return b
df["brand"] = df.apply(_repair_label, axis=1)

# Google News interest LEVEL (display), merged by qid from the news collection.
_news_path = REFRESH / "gtrends_news_500.csv"
if _news_path.exists():
    _nl = pd.read_csv(_news_path)[["qid", "news_level_basket1000"]].rename(
        columns={"news_level_basket1000": "news_level"})
    df = df.merge(_nl, on="qid", how="left")
else:
    df["news_level"] = pd.NA

# August VGR interest RECONSTRUCTED under the same 50/30/20 method, so the VGR
# "% vs last month" is a true like-for-like delta. Source: reconstruct_aug_vgr.py.
aug_rank, aug_index = {}, {}
with open(REFRESH / "aug_vgr_reconstructed.csv", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        try:
            aug_rank[r["qid"]] = int(float(r["aug_rank"]))
        except (KeyError, ValueError):
            pass
        try:
            aug_index[r["qid"]] = float(r["vgr_aug"])
        except (KeyError, ValueError):
            pass

# Reference the headline VGR interest to the SAME frozen 8-brand basket used by
# the Google sub-indices, whose average = 1,000. This puts VGR interest, g search
# and g news all on one 1,000 baseline. It is a monotonic rescale: ranks and
# tiers are unchanged, and because the identical factor scales both September and
# the reconstructed August, the like-for-like MoM % is unaffected.
BASKET = ["Nike", "Adidas", "Zara", "H&M", "Hermès", "Louis Vuitton", "Gucci", "Uniqlo"]
_basket_mean = df.loc[df["brand"].isin(BASKET), "interest_index"].mean()
SCALE = 1000.0 / _basket_mean if _basket_mean and not pd.isna(_basket_mean) else 1.0
df["interest_index"] = df["interest_index"] * SCALE
aug_index = {q: v * SCALE for q, v in aug_index.items()}
# Tier cut-offs (defined at 66 / 33 on the old top-5=100 scale) rescaled to match.
TIER_A_LO, TIER_B_LO, TIER_B_HI = round(66 * SCALE), round(33 * SCALE), round(65 * SCALE)


def vgr_mom_val(cur, qid):
    """Numeric VGR interest MoM percent, or None if the brand is new in August."""
    prev = aug_index.get(qid)
    if prev is None or prev == 0:
        return None
    return (float(cur) - prev) / prev * 100.0


def vgr_mom(cur, qid):
    v = vgr_mom_val(cur, qid)
    if v is None:
        return '<span style="color:#8a8f99;font-size:11px">new</span>', ""
    if v > 0:
        color, arrow = "#1a7a3a", "▲"
    elif v < 0:
        color, arrow = "#b3122b", "▼"
    else:
        color, arrow = "#666", "•"
    return (f'<span style="color:{color};font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap">'
            f'{arrow}&nbsp;{v:+.0f}%</span>', f"{v:.1f}")


n = len(df)
mx_idx = float(df["interest_index"].max()) or 1.0

# ---- rows ----------------------------------------------------------------------
rows_html = []
for _, r in df.iterrows():
    idx = float(r["interest_index"])
    brand = esc(r["brand"])
    vmom_html, _ = vgr_mom(idx, r["qid"])
    search_html, search_sort = fmt_level(r.get("trends_score"))
    smom_html, smom_sort = mom_badge_grey(r.get("search_mom"))
    pv_html, pv_sort = fmt_int(r.get("pv_median"))
    wmom_html, wmom_sort = mom_badge_grey(r.get("wiki_mom"))
    nlvl_html, nlvl_sort = fmt_level(r.get("news_level"))
    nmom_html, nmom_sort = mom_badge_grey(r.get("news_mom"))
    vmom_sort = f"{(vgr_mom_val(idx, r['qid']) or 0):.1f}"
    rows_html.append(
        f'<tr data-brand="{esc(str(r["brand"]).lower())}" data-tier="{r["tier"]}" '
        f'data-rank="{int(r["rank"])}" data-index="{idx:.1f}" data-vgrmom="{vmom_sort}" '
        f'data-trends="{search_sort}" data-searchmom="{smom_sort}" '
        f'data-pv="{pv_sort}" data-wikimom="{wmom_sort}" '
        f'data-newslvl="{nlvl_sort}" data-newsmom="{nmom_sort}">'
        f'<td class="num">{int(r["rank"])}</td>'
        f'<td><a href="https://www.wikidata.org/wiki/{r["qid"]}" target="_blank" rel="noopener">{brand}</a></td>'
        f'<td><span class="badge {r["tier"]}">{r["tier"]}</span></td>'
        f'<td class="num vgr-l"><div class="idxcell"><div class="mini"><i style="width:{idx/mx_idx*100:.0f}%"></i></div>'
        f'<span class="vgrval">{idx:,.0f}</span></div></td>'
        f'<td class="num">{vmom_html}</td>'
        f'<td class="num det det-l">{search_html}</td>'
        f'<td class="num det">{smom_html}</td>'
        f'<td class="num det det-l">{nlvl_html}</td>'
        f'<td class="num det">{nmom_html}</td>'
        f'<td class="num det det-l">{pv_html}</td>'
        f'<td class="num det">{wmom_html}</td></tr>'
    )

# ---- tiers
tc = df["tier"].value_counts().to_dict()
tiers_html = "".join(
    f'<div class="tcard {cls}"><div class="n">{int(tc.get(t,0))}</div>'
    f'<div class="l">{lab}</div><div class="rng">index {rng}</div></div>'
    for cls, t, lab, rng in [("a","A","A — elite",f"≥ {TIER_A_LO:,}"),("b","B","B — established",f"{TIER_B_LO:,}–{TIER_B_HI:,}"),("c","C","C — long tail",f"< {TIER_B_LO:,}")]
)

# ---- chart top 20
lead = df.head(20)
cmax = float(lead["interest_index"].max()) or 1.0
chart_html = "".join(
    f'<div class="bar {"lead" if i==0 else ""}"><div class="nm">{esc(r["brand"])}</div>'
    f'<div class="track"><div class="fill" style="width:{float(r["interest_index"])/cmax*100:.1f}%"></div></div>'
    f'<div class="v">{float(r["interest_index"]):,.0f}</div></div>'
    for i, (_, r) in enumerate(lead.iterrows())
)

# ---- movers: Aug -> refreshed Sept rank change
moves = []
for _, r in df.iterrows():
    a = aug_rank.get(r["qid"])
    if a is not None:
        moves.append((r["brand"], a - int(r["rank"])))
risers = sorted(moves, key=lambda x: -x[1])[:7]
fallers = sorted(moves, key=lambda x: x[1])[:4]
def mv_bars(items):
    out = []
    for name, dv in items:
        col = "#1a7a3a" if dv > 0 else "var(--red-dk)"
        w = min(100, abs(dv) * 2)
        out.append(f'<div class="bar"><div class="nm">{esc(name)}</div>'
                   f'<div class="track"><div class="fill" style="width:{w:.0f}%;background:{col}"></div></div>'
                   f'<div class="v">{"+" if dv>0 else ""}{dv}</div></div>')
    return "".join(out)
movers_html = mv_bars(risers) + mv_bars(fallers)

# ---- weights panel
wspec = [("Google search (basket=1,000)", 50), ("Google news (basket=1,000)", 30),
         ("Wikipedia pageviews", 20)]
weights_html = "".join(
    f'<div class="wrow"><span class="wname">{nm}</span>'
    f'<span class="wbar"><i style="width:{p}%"></i></span>'
    f'<span class="wpct">{p}%</span></div>' for nm, p in wspec
)

gen = datetime.now().strftime("%d %b %Y")
repl = {
    "%%LOGO_DATAURI%%": logo_uri(),
    "%%DECK%%": esc(DECK),
    "%%META%%": f"<b>{MONTH}</b> · {n} brands · 8-brand basket = 1,000 · GDELT + Reddit removed · generated {gen}",
    "%%TIERS%%": tiers_html,
    "%%CHARTSUB%%": f"Interest index, top 20 of {n}",
    "%%CHART%%": chart_html,
    "%%MOVERSTITLE%%": "Biggest movers",
    "%%MOVERSSUB%%": "Rank change, August → refreshed September",
    "%%MOVERS%%": movers_html,
    "%%ROWS%%": "".join(rows_html),
    "%%N%%": str(n),
    "%%GEN%%": "Refreshed September 2026 shot · GDELT + Reddit dropped · score = google search 50% / google news 30% / wikipedia 20%.",
    "%%WEIGHTS%%": weights_html,
    "%%ATT_PCT%%": "85",
    "%%BREADTH_PCT%%": "15",
}
out = TEMPLATE.read_text(encoding="utf-8")
for k, v in repl.items():
    out = out.replace(k, v)

NEW_HEAD = (
    '<thead>'
    '<tr class="grouprow">'
    '<th class="grp-id" colspan="3"></th>'
    '<th class="grp-vgr vgr-l" colspan="2">VGR</th>'
    '<th class="grp-det det-l" colspan="2">google search</th>'
    '<th class="grp-det det-l" colspan="2">google news</th>'
    '<th class="grp-det det-l" colspan="2">wikipedia</th>'
    '</tr>'
    '<tr class="labelrow">'
    '<th class="num" data-k="rank" data-t="n">#</th>'
    '<th data-k="brand" data-t="s">Brand</th>'
    '<th data-k="tier" data-t="s">Tier</th>'
    '<th class="num vgr-l" data-k="index" data-t="n">VGR interest</th>'
    '<th class="num" data-k="vgrmom" data-t="n">% vs last mo</th>'
    '<th class="num det det-l" data-k="trends" data-t="n" '
    'title="Google Trends search interest, referenced to a frozen 8-brand basket (Nike, Adidas, Zara, H&amp;M, '
    'Herm&egrave;s, Louis Vuitton, Gucci, Uniqlo) whose average = 1,000 — comparable across brands and across seasons">'
    'g search index</th>'
    '<th class="num det" data-k="searchmom" data-t="n">% vs last mo</th>'
    '<th class="num det det-l" data-k="newslvl" data-t="n" '
    'title="Google News search interest, anchor-chained the same way as g search and referenced to the same '
    'frozen 8-brand basket (average = 1,000) but measured on Google News — comparable across brands and seasons">'
    'g news index</th>'
    '<th class="num det" data-k="newsmom" data-t="n">% vs last mo</th>'
    '<th class="num det det-l" data-k="pv" data-t="n">wikipedia</th>'
    '<th class="num det" data-k="wikimom" data-t="n">% vs last mo</th>'
    '</tr>'
    '</thead>'
)
out = re.sub(r"<thead>.*?</thead>", lambda m: NEW_HEAD, out, count=1, flags=re.S)

out = out.replace(
    "thead th.num{text-align:right}",
    "thead th.num{text-align:right}\n"
    "  thead tr.grouprow th{top:0;padding:5px 8px;border-bottom:none;text-transform:none;\n"
    "    text-align:center;cursor:default}\n"
    "  thead tr.labelrow th{top:25px}\n"
    "  thead th.grp-id{background:var(--paper);border-bottom:none}\n"
    "  thead th.grp-vgr{color:var(--ink);font-weight:800;font-size:12px;letter-spacing:.10em}\n"
    "  thead th.grp-det{color:#9aa0aa;font-weight:600;font-size:10px;letter-spacing:.04em;text-transform:lowercase}\n"
    "  .vgr-l{border-left:2px solid var(--ink)}\n"
    "  .det-l{border-left:1px solid var(--hair)}\n"
    "  tbody td.det{color:#9aa0aa;font-size:11.5px}\n"
    "  thead th.det{color:#9aa0aa;font-weight:600;text-transform:lowercase}\n"
    "  .vgrval{font-weight:800;font-size:14px}\n"
    "  thead th{cursor:pointer;user-select:none}\n"
    "  thead th.sorted{color:var(--red)}\n"
    "  thead th[data-dir=\"up\"]::after{content:\" \\25B2\";font-size:9px}\n"
    "  thead th[data-dir=\"down\"]::after{content:\" \\25BC\";font-size:9px}")

out = out.replace("%%ATT_PCT%%% of the score — four signals",
                  "%%ATT_PCT%%% of the score — three signals")
out = out.replace(
    "The four signals below, each √-scaled against the top-5 brands then blended by\n"
    "          the weights shown. If a brand is missing a signal, the weights renormalise over the ones it\n"
    "          has (a source with no value is dropped, never counted as zero).",
    "Three signals — Google (web) search interest 50%, Google News interest 30%, and Wikipedia pageviews "
    "20% — each √-scaled against the top-5 brands, then blended by the weights shown. If a brand is missing "
    "a signal the weights renormalise over the ones it has (a source with no value is dropped, never counted "
    "as zero), so a brand with no trusted news level scores on search + pageviews reweighted. Both Google "
    "levels are made cross-brand comparable by anchor-chaining every query, then referenced to a frozen "
    "8-brand basket (Nike, Adidas, Zara, H&amp;M, Herm&egrave;s, Louis Vuitton, Gucci, Uniqlo) whose average "
    "= 1,000 as of the Sept-2026 base window — so the numbers are comparable across brands and stay on a "
    "stable scale across seasons, and g search index and g news index sit on the same 1,000-average scale. "
    "Brands whose search term resolved to the wrong entity are excluded, as are very small brands below "
    "Trends' integer resolution; the news level carries the same trust gate (topic-entity match, web-trusted), "
    "so ~138 brands earn a news score and the rest fall back to search + pageviews. GDELT and Reddit were "
    "removed as signals. In the table, the VGR interest and its month-over-month change lead each row; the "
    "per-source detail (google search, google news, wikipedia) is shown greyed alongside with each source's "
    "month-over-month change.")

NEW_JS = (
    'let sortK=null, asc=false;\n'
    '  const heads=[...document.querySelectorAll("#tbl thead th[data-k]")];\n'
    '  function mark(){ heads.forEach(th=>{ const on=th.dataset.k===sortK;\n'
    '    th.classList.toggle("sorted", on);\n'
    '    if(on) th.setAttribute("data-dir", asc?"up":"down"); else th.removeAttribute("data-dir"); }); }\n'
    '  function doSort(k,t){\n'
    '    const sorted = rows.slice().sort((a,b)=>{\n'
    '      let x=a.dataset[k], y=b.dataset[k];\n'
    '      if(t=="n"){ x=parseFloat(x); y=parseFloat(y); x=isNaN(x)?-1:x; y=isNaN(y)?-1:y; return asc?x-y:y-x; }\n'
    '      x=x||""; y=y||""; return asc?x.localeCompare(y):y.localeCompare(x);\n'
    '    });\n'
    '    sorted.forEach(r=>tbody.appendChild(r)); mark();\n'
    '  }\n'
    '  heads.forEach(th=>th.addEventListener("click", ()=>{\n'
    '    const k=th.dataset.k, t=th.dataset.t;\n'
    '    if(!k) return;\n'
    '    if(k===sortK) asc=!asc; else { sortK=k; asc=(k=="brand"||k=="tier"); }\n'
    '    doSort(k,t);\n'
    '  }));\n'
    '  sortK="index"; asc=false; doSort("index","n");'
)
out = re.sub(
    r'let sortK="rank", asc=true;.*?sorted\.forEach\(r=>tbody\.appendChild\(r\)\);\s*\}\)\);',
    lambda m: NEW_JS, out, count=1, flags=re.S)

out = out.replace("Google Trends, Wikipedia pageviews, GDELT news, Reddit, Wikidata",
                  "Google Trends, Wikipedia pageviews, Google News, Wikidata")

OUT_HTML.write_text(out, encoding="utf-8")
print(f"wrote {OUT_HTML}  ({OUT_HTML.stat().st_size:,} bytes)")

# ---- JSON data feed (CORS-open once on GitHub Pages) ---------------------------
def jnum(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        f = float(v)
        return round(f, 2)
    except (TypeError, ValueError):
        return None

brands = []
for _, r in df.iterrows():
    idx = float(r["interest_index"])
    brands.append({
        "rank": int(r["rank"]),
        "brand": str(r["brand"]),
        "qid": str(r["qid"]),
        "tier": str(r["tier"]),
        "interest_index": round(idx, 1),
        "vgr_mom_pct": (round(vgr_mom_val(idx, r["qid"]), 1)
                        if vgr_mom_val(idx, r["qid"]) is not None else None),
        "aug_rank": aug_rank.get(r["qid"]),
        "trends_level": jnum(r.get("trends_score")),
        "search_mom_pct": pctnum(r.get("search_mom")),
        "news_level": jnum(r.get("news_level")),
        "news_mom_pct": pctnum(r.get("news_mom")),
        "wikipedia_pageviews": (int(round(float(r["pv_median"])))
                                if pd.notna(r.get("pv_median")) else None),
        "wiki_mom_pct": pctnum(r.get("wiki_mom")),
        "wikidata_url": f"https://www.wikidata.org/wiki/{r['qid']}",
    })

feed = {
    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "month": MONTH,
    "n_brands": n,
    "scale": "8-brand basket = 1000",
    "method": {
        "google_search_pct": 50, "google_news_pct": 30, "wikipedia_pct": 20,
        "attention_pct": 85, "breadth_pct": 15,
        "basket": ["Nike", "Adidas", "Zara", "H&M", "Hermès",
                   "Louis Vuitton", "Gucci", "Uniqlo"],
        "basket_average": 1000,
    },
    "tiers": {t: int(tc.get(t, 0)) for t in ("A", "B", "C")},
    "top20": [{"brand": str(r["brand"]), "interest_index": round(float(r["interest_index"]), 1)}
              for _, r in lead.iterrows()],
    "movers": {
        "risers": [{"brand": nm, "rank_change": dv} for nm, dv in risers],
        "fallers": [{"brand": nm, "rank_change": dv} for nm, dv in fallers],
    },
    "brands": brands,
}
OUT_JSON.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {OUT_JSON}  ({OUT_JSON.stat().st_size:,} bytes, {n} brands)")
print("top5 movers up:", risers[:5])
print("top movers down:", fallers)
