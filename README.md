# VGR Brand Index — data pipeline

A fashion-brand *attention* tracker: ranks 60 brands on a single 0–100 scale
from free, retroactive public sources. This repo is the **data pipeline only**
(fetchers, normalisation, backtest, Supabase load). The public pages that read
from Supabase are built separately in Lovable.

Stack: Python 3.13, [uv](https://docs.astral.sh/uv/), pandas, httpx, pytest.
No paid APIs.

## Sources

| Source | Signal | Depth |
|---|---|---|
| Wikipedia pageviews | Entity curiosity | Daily, back to 2015 — the backbone |
| GDELT | News mention volume | Back to 2017 |
| Google Trends (pytrends) | Search interest | Deep but fragile |

Every brand is keyed on its **Wikidata Q-ID**, never an article title. One Q-ID
resolves to the correct article in every language edition, survives renames,
and keeps homonyms apart (`Mango` the retailer vs. the fruit are different
Q-IDs, so the ambiguity never enters the data).

## Build phases

The pipeline is built and reviewed in gated phases:

1. **Entity resolution** ✅ — resolve every brand to a Q-ID + per-language
   article titles; produce a resolution report for manual review.
2. Fetchers — one module per source, common `fetch(entity, start, end)` interface, disk-cached.
3. Normalisation — log → z-score (104-week window) → inverse-variance weight, per-source eligibility flags.
4. Backtest — does the composite track/lead reported quarterly sales? (the real deliverable)
5. Supabase schema + weekly refresh.

## Phase 1 — entity resolution

```bash
uv run vgr-resolve          # or: uv run python -m vgr_brand_index.resolve
```

Reads [`brands.yaml`](brands.yaml) (60 brands, four tiers of 15) and writes
`output/resolution.csv` — one row per brand with its Q-ID, matched label,
Wikidata description, coverage flag, and the article title in each of the seven
tracked languages (`en es fr it de ja zh`).

**Resolution never trusts the first search hit.** It searches Wikidata, fetches
each candidate's sitelinks in one batched call, then — walking the search's own
relevance order — picks the first candidate that both reads as a fashion/retail
entity *and* has an English Wikipedia article (the en pageview series is the
index backbone). Brands the spec flags as ambiguous, plus every hand-verified
disambiguation, are pinned by Q-ID in `brands.yaml` with a rationale note.

### What Phase 1 found

Of 60 brands: **54 resolve cleanly** (Q-ID + English article). The rest are
honest coverage gaps in a Wikipedia-backed index, recorded rather than faked:

| Coverage | Brands | Handling |
|---|---|---|
| French Wikipedia only, no en | Sézane, Arket, Maje | Usable — non-en pageviews only |
| Valid Q-ID, no article anywhere | Nanushka | Wikipedia ineligible |
| No Wikipedia entity at all | Totême, Reformation | Wikipedia ineligible — GDELT/Trends only |

These feed directly into the per-entity **source eligibility flags** in Phase 3:
a brand with no English article isn't zero-filled, its Wikipedia weight is
dropped and the remaining sources renormalised.

## Layout

```
brands.yaml                     60-brand seed list + verified Q-ID pins
src/vgr_brand_index/
  wikidata.py                   Wikidata client, candidate scoring, selection
  resolve.py                    Phase 1 entrypoint -> output/resolution.csv
tests/test_choose.py            no-network tests for the selection rule
cache/                          raw API responses (gitignored, re-runs read these)
output/                         generated reports (gitignored)
```
