# VGR Brand Index — data pipeline

A fashion-brand *attention* tracker: ranks the top **500** brands on a single
interest scale and tiers them **A / B / C**, from free, retroactive public
sources. This repo is the **data pipeline only** (universe, fetchers,
normalisation, backtest, load). The public pages that read from it are built
separately in Lovable.

Stack: Python 3.13, [uv](https://docs.astral.sh/uv/), pandas, httpx, pytest.
No paid APIs. **Never fabricate, estimate or interpolate a data point — missing
is missing.**

## The index in one screen

```bash
uv run python -m vgr_brand_index.interest
```

Writes `output/index_500.csv` — the ranked, A/B/C-tiered top 500 — and
`output/index_full_ranked.csv` (the full scored pool, for audit).

## Method

### 1. Universe — queried, never typed

The 500 are not hand-listed (which would risk inventing brands or wrong Q-IDs).
The candidate universe is **queried from Wikidata** so every brand arrives with
a real Q-ID already attached, and global groups are naturally decomposed — each
banner (Zara, Bershka, Pull&Bear …) is its own Wikidata item, which is exactly
the VGR-50 criterion.

Recall is a union of the productive Wikidata roots (chosen by counting entities
per root, `universe.py`):

- **instance of** `fashion brand`, `fashion house`
- **industry** = fashion · clothing · shoe · sporting goods · sportswear · luxury goods

`textile industry` (fabric mills) and the product-instance classes (individual
shoes/equipment) are excluded as noise. This yields ~2,465 distinct brands,
~875 with an English Wikipedia article.

### 2. Interest — a blend of breadth and attention

Per brand, two free signals:

| Signal | What it captures | Source |
|---|---|---|
| Wikipedia **sitelink count** | breadth of global notability | Wikidata |
| Trailing-12-month **English pageviews** | current attention | Wikimedia REST |

Each is `sqrt`-transformed (the variance-stabilising transform for count data —
tames the heavy tail without erasing real concentration the way `log` does),
expressed as a **ratio to the mean of that signal's top 5**, then blended
**50 / 50**.

> Pageviews use English Wikipedia only — the index backbone and the single most
> comparable global attention series. Cross-language breadth is already rewarded
> by the sitelink half, so a French-only brand still earns interest. A brand with
> no English article scores 0 pageviews (a real 'no signal', not an estimate) and
> rides on sitelinks. Multi-language pageview blending is a later refinement.

### 3. Index — anchored to the top 5

The blended score is scaled so the **mean of the top 5 brands = 100**:

```
interest_index = blended_score / mean(top-5 blended_score) × 100
```

### 4. Tiers — A / B / C on the top-5-anchored scale

| Tier | Interest index | Meaning |
|---|---|---|
| **A** | ≥ 66 | elite (~26 brands) |
| **B** | 33 – 65 | established (~108) |
| **C** | < 33 | the long tail (~366) |

Then the **top 500** by interest are kept. Tier sizes fall out of the real
concentration of attention — a small A, a broad C.

### Review flags

The pipeline **flags but never drops** parent groups / holding companies
(Inditex, Tapestry, Capri, SMCP …), which the VGR rule keeps out of the brand
layer, plus obvious non-brands. The exclusion decision stays with the human
review at the gate (`review_flag` column).

## Layout

```
src/vgr_brand_index/
  universe.py     query the brand universe from Wikidata (union of roots)
  pageviews.py    Wikimedia REST pageviews (interest window + Phase-2 daily)
  interest.py     blend -> index -> A/B/C -> top 500  (entrypoint)
  wikidata.py     Wikidata client (Q-ID resolution, sitelinks, labels)
  resolve.py      legacy: the original hand-curated 60-brand resolver
tests/            no-network unit tests
cache/            raw API responses (gitignored — re-runs read these)
output/           generated index CSVs (gitignored)
```

## Build phases

0. **Universe + interest index** ✅ — the 500-brand A/B/C leaderboard.
1. ~~60-brand entity resolution~~ — superseded by the queried universe (kept as `resolve.py`).
2. Fetchers — GDELT + Google Trends alongside pageviews, common interface, cached.
3. Normalisation — log → z-score (104-week window) → inverse-variance weight, per-source eligibility flags.
4. Backtest — does the composite track/lead reported quarterly sales? (the real deliverable)
5. Supabase schema + weekly refresh.
