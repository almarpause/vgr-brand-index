# Roster rebrand + re-collection (Sept 2026)

**Objective (user, 2026-09-08):**
1. Disambiguation → pick the **highest-traffic** entity (worldwide) when a brand name is ambiguous.
2. Always **worldwide** geo (already default `geo=""`; add guard).
3. **Add Adidas** as a real ranked brand (it was only the anchor).
4. **Remove 4 sub-brands/collabs:** Adidas Originals (Q4682711), Adidas Yeezy (Q22101752), Yeezy Gap (Q96657862), Yeezy (Q96791543).
5. **Normalize all ~25 corporate names** to consumer brand form (Levi's, North Face, Lululemon, On, Ralph Lauren, Timberland, Benetton, Mizuno, …) — homogeneous roster.
6. **Exactly 500** brands. Backfill from next-ranked Wikidata candidates (pool of 112 already have pageviews; need Trends).

**Decisions (user-confirmed):** backfill = next-ranked Wikidata brands; remove all four sub-brands; normalize all corporate names.

## Key facts discovered
- Roster = `output/2026-09/index_500.csv` (500 rows, keyed by qid). Membership correct; Sept-1 auto-build lost pv (all 0) so scores were rebuilt in `refresh_500/`.
- Canonical rebuild scripts: `scratchpad/rebuild_refresh.py` (index) + `scratchpad/build_dashboard_refresh.py` (dashboard). Output: `refresh_500/index_500_refreshed.csv`, `refresh_500/dashboard_refreshed.html`.
- Trends level column: `gtrends_web_500.csv:trends_level_basket1000` (frozen 8-brand basket=1000; see `baseline_basket.json`). Scale-invariant → rescaling never changes ranks.
- **Adidas = Q3895, NOT in the Wikidata universe** (roots miss it; Nike=Q483915 was caught). Force-add like EXTRA_QIDS. Trends level already known (anchor=100 → basket 2285.7). Needs **pageviews** collected.
- **Backfill pool** = 112 brands in `refresh_500/wiki_500.csv` beyond the 500, WITH pageviews but NO trends. Top by pv: Gymshark, TK Maxx, Eddie Bauer, Fashion Nova, COS, Psycho Bunny, Brunello Cucinelli…
- Geo already worldwide (`trends.py` `geo=""`).

## Plan / status — ALL DONE (2026-09-08)
- [x] STAGE A — roster surgery: `refresh_500/build_roster_v2.py` -> `roster_500_v2.csv` (500 rows). Config in `roster_surgery.json`.
- [x] STAGE B — resolver upgrade: `resolve_query` now compares brand-type candidates' worldwide traffic (`_pick_highest_traffic`) + worldwide guard. `src/vgr_brand_index/trends.py`.
- [x] STAGE C — `refresh_500/stage_c_trends.py`: qmap aligned (24 renames + On repaired); Adidas row (basket 2285.74); backfill Trends (TK Maxx 108.57, Eddie Bauer 38.86, Gymshark 5.65 via TK-Maxx bridge). Backups `gtrends_web_500.csv.bak_stagec`.
- [x] STAGE D — Adidas pageviews via `signals._pv_monthly` (99 editions): pv_median 180,671. Appended to `wiki_500.csv` (bak `.bak_adidas`).
- [x] STAGE E — rebuilt. `index_500_refreshed.csv` (500 rows) + `dashboard_refreshed.html` (621KB). **Adidas #1 (129.5 A)**, Nike #2. Levi's/The North Face/etc. clean. No sub-brands. Backfill: TK Maxx #94, Gymshark #114, Eddie Bauer #122.

## Table redesign (2026-09-09)
- `scratchpad/build_dashboard_refresh.py` rewritten to the user's grouped-"subset" layout:
  Position | Brand | Tier, then a PROMINENT **VGR** subset (VGR interest w/ mini-bar + bold value,
  and "% vs last month" = MoM% of interest_index vs Aug — coloured), then three de-emphasised
  (grey + lowercase) subsets: **google search** (g search index = basket-1000 level + search_mom),
  **wikipedia** (pv_median + wiki_mom), **news** (g news · yoy + news_mom).
- Two-row sticky header (group row + metric-label row). VGR group dark/bold; source groups grey/lowercase.
- **News is now a real anchor-chained LEVEL** (2026-09-09, replaces the momentum-only slot). The
  "g news index" column reproduces the g-search method exactly on Google News (`gprop="news"`):
  same topic tokens, same Adidas anchor-chaining, rescaled to the SAME frozen 8-brand basket (avg =
  1,000). Second news column stays `news_mom` (% vs last month). **Display-only** — does NOT feed
  the VGR score (pv 0.65 / trends 0.30 unchanged), per user 2026-09-09.
  - Collector: `scratchpad/collect_news_levels.py` → `refresh_500/gtrends_news_500.csv`
    (cols: qid, brand, token, news_level_adidas100, news_level_basket1000, trusted). Checkpoint:
    `news_levels_checkpoint.json`; log `collect_news.log`. Reuses web tokens from
    `gtrends_web_500.csv` (topic mids are property-independent → no re-resolution, dodges On/Next
    bare-word regression). News basket ref (geomean of 8) = 38.0494, rescale ×26.2816.
  - **Trust gate:** a news level is shown ONLY where the WEB level was trusted — token is a topic
    mid AND web `trends_level_basket1000` non-empty AND not `suspect_inflated`. News volume is
    dominated by wrong-sense entities (Munich=city, Beer=beverage, raw keywords "George"/"HEAD"),
    so ungated it's garbage (233 raw → top was GU 30k). Gated: **138/504 brands show a level**; top
    reads Nike 4,368 · Adidas 2,628 · Shein 2,356 · Zara 1,278 · H&M 734 · LV 710 (credible).
    Raw adidas100 kept in CSV for transparency; `trusted` col flags 0/1.
  - `gprop` support added to `src/vgr_brand_index/trends.py` (`__init__` param, folded into
    `_cache_path` key + `batch_news_*` filename, passed to `build_payload`). Cached so re-runs
    resume free. NOT yet wired into the live `run_monthly` pipeline (refresh-only this cycle).
- Dashboard merges `news_level` by qid at build time (kept OUT of `index_500_refreshed.csv` so it
  never touches scoring). Output: `refresh_500/dashboard_refreshed.html` (~636 KB). Verified
  in-browser: two-row header with "g news index", gated brands dash, sort-by-news credible, UTF-8
  clean. Build console fixed (`sys.stdout.reconfigure` utf-8) — no more ı/ü crash.

## Pipeline permanence (2026-09-09) — DONE in `src/vgr_brand_index/universe.py`
- **Adidas (Q3895)** added to `EXTRA_QIDS` (force-included; no root catches it).
- **`DROP_QIDS`** frozenset (Q4682711, Q22101752, Q96657862, Q96791543) filtered from BOTH roots
  and extras — the 4 sub-brands/collabs can never re-enter.
- **`BRAND_RENAMES`** dict (28 qid→consumer-name entries, ported from `roster_surgery.json`)
  applied in `_row_to_item`, so labels normalise on every run (Levi's, The North Face, Lululemon,
  On, Stüssy=U+00FC, …). Pageviews are qid-keyed → backbone unaffected by the label change.
- Live path confirmed: `run_monthly` → `interest.build_index` → `fetch_universe` / `_row_to_item`.
- **Known nuance:** two renamed labels are common English words — "On" (Q43452713) and "Next"
  (Q246655). `signals._is_ambiguous_name` gates string-search sources (Trends/News) OFF for
  common-word names, so in the LIVE pipeline On/Next score on **pageviews only** (Trends fetched but
  dropped at eligibility). To let their verified Trends tokens count, whitelist them past the gate
  + pin their tokens (not yet done). Pageviews dominate weight, so rank impact is small.

## VGR "% vs last month" fixed via reconstructed August (2026-09-09) — DONE (refresh)
- **Problem:** the VGR "% vs last month" compared the new 50/30/20 September index to
  `output/2026-08/index_500.csv`, which was built under the OLD 4-source method (no news,
  old weights) and has **no Adidas row** (Adidas was only the anchor then) → invalid for every
  brand; Adidas rendered "new". VGR interest is cross-sectional (each brand vs that month's top-5),
  so a valid MoM needs the WHOLE August cross-section re-scored under 50/30/20.
- **Fix (fast reconstruction):** `scratchpad/reconstruct_aug_vgr.py`. For each brand
  `aug_level = sep_level/(1+MoM)` for google search & google news (their `search_mom`/`news_mom`
  are the brand's own level momentum); **pv held flat** (pv_median is a trailing-12 median, ~stable
  MoM, and the raw monthly series isn't stored; 20% weight). Re-scores the Aug cross-section with the
  identical engine (sqrt_ratio_to_top5 → combine_sources 50/30/20 → 0.15·breadth+0.85·att →
  /top5·100). **Validation: reconstructing SEPT reproduces the stored interest_index exactly
  (max abs diff 0.00).** Coverage 500/500.
- **Adidas** was never collected (anchor), so its own momentum came from a tiny targeted Trends
  fetch here: **search_mom −1.2%, news_mom +22.9%** (cached to `refresh_500/adidas_mom_cache.json`).
  Result: **Adidas Sep VGR 119.8 vs reconstructed Aug 127.0 → −5.7% (renders −6%)** — it fell because
  Nike rose +6.5% and overtook it, lifting the top-5 benchmark (Adidas's own signal was ~flat).
- **Output:** `refresh_500/aug_vgr_reconstructed.csv` (qid, brand, rank, aug_rank, vgr_sep, vgr_aug,
  vgr_mom_pct). Dashboard now sources BOTH the VGR "% vs last month" AND the movers panel (Aug→Sep
  rank change) from this reconstructed Aug baseline (was the old broken file).
- **Caveat:** approximation — browser-collected per-source MoM references differ slightly from the
  frozen-basket level, and pv is held flat. Gold-standard alternative (not done): 24-month WEEKLY
  re-collection (web+news) preserving the series, sliced into trailing-12 windows for Aug and Sep.

## Weighting change: news promoted to a scored source — 50/30/20 (2026-09-09) — DONE (refresh)
- User decision (supersedes the 55/45 pv/trends split below): the VGR score is now
  **google search 50% / google news 30% / wikipedia 20%**. **News is no longer display-only** —
  it feeds the score.
- **Refresh applied** (`scratchpad/rebuild_refresh.py`): `WEIGHTS = {"trends":0.50,"news":0.30,"pv":0.20}`,
  `SOURCES = ["trends","news","pv"]`. News level = `gtrends_news_500.csv:news_level_basket1000`
  (trust-gated; blank → ineligible). New `elig_news`, `news_score` column, `news_ratio`. Coverage at
  run: trends 272, **news 136**, pv 475 eligible (all > MIN_COV=60). `combine_sources` renormalises
  per brand, so a brand with no trusted news level scores on search+pv reweighted (50/20 → 71.4/28.6).
- **Dashboard** (`scratchpad/build_dashboard_refresh.py`): subsets reordered L→R to
  **google search | google news | wikipedia** (group row, label row, and body cells); weights panel
  → 50/30/20; method copy → "three signals" (news no longer display-only). **VGR interest mini-bar
  left-justified** — `dashboard_template.html` `.idxcell` `justify-content:flex-end` → `flex-start`.
- **Result:** ranks shift toward search/news-led attention. **Nike #1 (130.5)**, Adidas #2 (119.8),
  Shein #3 (86.9), Zara #4, H&M #5, Louis Vuitton #6, Uniqlo #7, Supreme #8 (search+pv only), Gucci #9,
  New Balance #10. Tiers A 8 / B 54 / C 438. `index_500_refreshed.csv` + `dashboard_refreshed.html` (637 KB) regenerated.
- **LIVE PIPELINE NOT YET UPDATED for the 3-source split.** `src/vgr_brand_index/interest.py` still
  has `SOURCE_WEIGHTS = {pv 0.55, trends 0.45, gdelt 0.03, reddit 0.02}` and no `news` source, because
  `signals.gather_signals` does not collect a Google News level yet (news collector is refresh-only).
  To make 50/30/20 permanent for Oct-1 `run_monthly`: wire the news collector into gather_signals
  (produce `news_score` + `elig_news`), add `"news"` to `DYNAMIC_SOURCES` and `raw_cols`, and set
  `SOURCE_WEIGHTS = {trends 0.50, news 0.30, pv 0.20}` (drop/retain gdelt+reddit as reserve). Not done
  to avoid half-wiring a source with no live data.

## Weighting change: 55/45 pv/trends (2026-09-09) — DONE (superseded above)
- User decision after the sensitivity study: move the pv/trends split from **65/30 → 55/45**.
- **Why:** `scratchpad/weight_sensitivity.py` (validated 100% against the stored 65/30 ranks)
  showed the split is a mid-tail nudge, not a top-order lever — top-20 untouched, Spearman ρ ≥ 0.99.
  55/45 = the sweet spot (median 4-place move, ~8 tier changes, top-20 fixed); 50/50 is the ceiling
  (past it trades away pv's topic-mid Q-ID reliability). More trends weight lifts search-strong /
  wiki-thin brands and lowers wiki-heavy / search-thin brands.
- **Applied in three places:**
  1. `scratchpad/rebuild_refresh.py` line 33 → `WEIGHTS = {"pv": 0.55, "trends": 0.45}` (refresh CSV).
  2. `src/vgr_brand_index/interest.py` line 58 `SOURCE_WEIGHTS` → pv 0.55 / trends 0.45 (gdelt 0.03 /
     reddit 0.02 reserve unchanged). `combine_sources` renormalises per brand over eligible sources,
     so with only pv+trends eligible the effective split is exactly 55/45 — Oct-1 `run_monthly` keeps it.
  3. `scratchpad/build_dashboard_refresh.py` weights panel + method copy (55% / 45%).
- **Regenerated:** `refresh_500/index_500_refreshed.csv` (500 rows; tiers A 11 / B 81 / C 408) and
  `refresh_500/dashboard_refreshed.html` (636 KB). Top-20 unchanged (Adidas #1 127.8, Nike #2 121.5,
  Zara #3, H&M #4, Uniqlo #5 …). Mid-tail movers as predicted.

## Key outcome / findings
- Renames are COSMETIC for Trends (lookup by qid; existing tokens already the correct brand entities — verified Levi's=Levi Strauss clothing co, On AG=/g/11dxprv1lg running brand, Next, Clarks). Re-resolving bare "On" would regress (word "on"), so kept qid-keyed tokens; new rule applies to backfill + future runs.
- Adidas Q3895 was never in the Wikidata universe roots — force-added like EXTRA_QIDS. **TODO for pipeline permanence:** add "Q3895" to `EXTRA_QIDS` in `src/vgr_brand_index/universe.py` and the 4 removed sub-brand qids to a drop-list so the Oct-1 `run_monthly` keeps these changes.
- Kept-as-written (real brand / holding, no consumer sub-brand): The Limited, Tiffany & Co., C.P. Company, Best Company, Ecko Unltd., IC Group, Çalık Holding.
- NOT yet propagated to `output/2026-09/index_500.csv` (published shot) or the pipeline defaults — these live in `refresh_500/`. Decide whether to overwrite the Sept shot or ship at Oct-1.

---

## Website publishing infrastructure (2026-09-09) — replicates VGR 40

Goal: get the 500-brand Brand Index onto the VGR website the same way VGR 40 is
published (GitHub Pages + a GitHub Action, embedded in Lovable via iframe or a
React component that reads a JSON feed).

**Template studied:** `C:\Users\aresi\Claude\code\vgr-index\` — `WEB_DEPLOY.md`,
`push.bat`, `dashboard.py`, `.github/workflows/refresh-index.yml`. VGR 40 repo:
`github.com/almarpause/vgr-fashion50.git`. Its Action re-pulls Yahoo live daily.

**Key difference:** the Brand Index's inputs (pytrends web+news, Wikipedia
pageviews) are rate-limited and collected LOCALLY, so the cloud Action does NOT
re-collect. It deterministically re-renders the site from the committed
`refresh_500/*.csv`. Refresh flow = re-run local collection → commit new CSVs →
push → Action republishes.

**Files created in brand-index (this milestone):**
- `dashboard.py` — project-resident port of scratchpad `build_dashboard_refresh.py`
  (project-relative paths). Writes `Brand_Index_Dashboard.html` (byte-identical to
  `refresh_500/dashboard_refreshed.html` modulo CSS comments) AND `brand_index_data.json`
  (CORS-open feed: method + all 500 brands: rank, tier, interest_index, vgr_mom_pct,
  aug_rank, trends/news levels, per-source mom%, wikipedia pageviews, wikidata_url;
  plus tiers, top20, movers). Reads index_500_refreshed.csv + gtrends_news_500.csv
  + aug_vgr_reconstructed.csv + dashboard_template.html + logo asset.
- `.github/workflows/refresh-index.yml` — "Refresh VGR Brand Index": on push to
  main/master + weekly Mon 06:00 UTC + manual dispatch. pip install
  requirements-web.txt → python dashboard.py → assemble site/ (index.html +
  brand_index_data.json) → upload-pages-artifact@v3 → deploy-pages@v4.
- `requirements-web.txt` — pandas>=2.2 (CI publish only; full pipeline stays local).
- `push.bat` — one-click push to `github.com/almarpause/vgr-brand-index.git` (branch
  master). NOTE: repo must be created empty on GitHub first.
- `WEB_DEPLOY.md` — the playbook (Steps 1-3 + iframe embed + `<BrandIndex />` React
  component reading the JSON feed, adapted from VGR 40's FashionIndex).

**Validation:** `python dashboard.py` runs clean; HTML matches existing dashboard
(comments-only diff); JSON valid, 500 brands, Nike #1/Adidas #2 (-5.7% MoM)/Shein
#3, tiers A8/B54/C438. CI assemble step simulated OK.

**NOT yet done (needs user action / explicit permission):**
1. Create empty GitHub repo `vgr-brand-index` under almarpause.
2. Push (`push.bat` or manual) — DEPLOY action, needs explicit go-ahead.
3. GitHub: Settings → Pages → Source: GitHub Actions; run the Action once.
4. Paste iframe or `<BrandIndex />` into the Lovable Intelligence page; set DATA_URL.
