# VGR Brand Score — data pipeline

A fashion-brand *attention* tracker: ranks the top **500** brands on a single
interest scale, tiers them **A / B / C**, refreshes on a **monthly cadence**, and
writes an Economist-styled **.docx report** for each monthly shot. Built from
free, retroactive public sources. €0 — no paid APIs.

Stack: Python 3.13, [uv](https://docs.astral.sh/uv/), pandas, httpx, matplotlib,
python-docx, pytrends. **Never fabricate, estimate or interpolate a data point —
missing is missing.**

## Two jobs, staggered and at night

Fetching is spread gently across the month so no endpoint is ever hammered;
assembly and the report happen once a month.

| Job | Cadence | Command | Does |
|---|---|---|---|
| **Nightly fetch** | daily 02:30 | `vgr-fetch-nightly` | fetches one shard (~1/28th) of brand signals into cache |
| **Monthly assemble** | 1st, 04:00 | `vgr-run-monthly` | scores from cache → shot + history → report → email |

```bash
uv run vgr-fetch-nightly            # today's shard (pageviews + GDELT + Trends)
uv run vgr-run-monthly --dry-run    # build this month's shot + report, no email
uv run vgr-run-monthly              # build + email the report
```

## Sources — all free, all keyless (except Trends' unofficial endpoint)

| Source | Signal | Depth | Role |
|---|---|---|---|
| Wikidata | universe, Q-IDs, sitelink breadth | current | selection + breadth |
| Wikipedia pageviews (all languages) | reader attention | 2015 → | attention |
| GDELT | news mention volume | 2017 → | attention |
| Google Trends (pytrends) | search interest | 2004 →* | attention (best-effort) |

Every brand is keyed on its **Wikidata Q-ID**, so homonyms stay separate and
global groups are already decomposed to banners. *Trends is an unofficial
endpoint: cached hard, retried, and dropped gracefully when blocked — a brand
simply carries no Trends signal and the composite renormalises over the rest.

## Method

1. **Universe** — queried from Wikidata by industry/instance roots (~2,465 brands).
2. **Signals** — per brand: all-language pageviews, GDELT volume, Trends interest,
   gathered by the nightly job into cache; the monthly job reads cache only.
3. **Attention composite** — each dynamic source is `sqrt`-scaled to its top-5 mean,
   then combined by inverse-variance weighting over the brand's **eligible** sources
   (missing sources dropped and renormalised, never zero-filled).
4. **Interest index** — `0.5 · sitelink breadth + 0.5 · attention composite`, scaled so
   the **top-5 average = 100**.
5. **Tiers** — **A ≥ 66 · B 33–65 · C < 33**; keep the **top 500**. Parent groups
   (Inditex, Tapestry …) are flagged and dropped, backfilled from rank 501+.

## Following the trend

Each run writes a dated shot (`output/<YYYY-MM>/`) and upserts the month into
`history/index_history.parquet`, keyed `(qid, month)` so re-running a month
corrects it in place. `deltas.py` reads history for the report: the winner and
its growth, biggest movers, and tier migrations (A↔B↔C, in/out of the 500) —
"who changed in the top and in the middle vs last month".

## The monthly report

`report.py` builds a VGR/Economist-navy `.docx` (engine + logo vendored under the
package, so the headless job needs no skills plugin): cover with logo, an
executive summary in **vgr-voice register** composed from the deltas, an
economist-chart-style figure, ledger tables (top of index, movers), method and
colophon. A separate Claude pass can rewrite the summary in full five-moves voice;
the facts do not change.

## Deploy (Windows Task Scheduler)

```powershell
# elevated PowerShell (SYSTEM, unattended) — or add -CurrentUser to run as you
powershell -ExecutionPolicy Bypass -File schedule\register_schedule.ps1
schtasks /Run /TN VBI-FetchNightly     # trigger one shard now
schtasks /Run /TN VBI-Monthly          # build + email now
powershell -ExecutionPolicy Bypass -File schedule\unregister_schedule.ps1
```

SMTP is reused from the Zara parser's git-ignored `email.ini` (path in
`config/settings.json`), overridable by `VBI_SMTP_*` / `ZARA_SMTP_*` env vars. No
secrets in this repo; with no credentials the email is skipped and the report is
still built and saved.

## Layout

```
src/vgr_brand_index/
  universe.py     query the brand universe from Wikidata
  pageviews.py    Wikipedia pageviews (all editions), cache + backoff
  gdelt.py        GDELT news volume, gentle throttle
  trends.py       Google Trends, anchor-chained, best-effort
  signals.py      gather all signals per brand (cache_only for scoring)
  normalize.py    sqrt-ratio, z-score, inverse-variance combination
  interest.py     compose -> index -> A/B/C -> top 500   (vgr-index)
  store.py        dated shots + append-only history
  deltas.py       month-over-month movers + migrations
  report.py       Economist .docx + chart (vendored economist_navy.py)
  emailer.py      SMTP send (reused external ini + env)
  fetch_nightly.py  one staggered shard        (vgr-fetch-nightly)
  run_monthly.py    assemble + report + email  (vgr-run-monthly)
schedule/         Task Scheduler registrar + .bat launchers
config/           settings.json (recipients, cadence, smtp_ini path)
history/          index_history.parquet (tracked)
cache/ output/ logs/   (gitignored)
```

## Build phases

0. Universe + interest index ✅
1. ~~60-brand entity resolution~~ — superseded (kept as `resolve.py`).
2. Four sources + normalisation + monthly shots + report + schedule ✅
3. Backtest — does the composite track/lead reported quarterly sales? (next)
4. Optional cloud: Supabase + Edge Function cron.
```
