"""GDELT news-mention volume fetcher — attention source #2.

Wraps the GDELT DOC 2.0 API (`api.gdeltproject.org/api/v2/doc/doc`), keyless and
free, covering worldwide news back to 2017. We use `timelinevolraw` — the raw
count of matching articles per time bin — and aggregate to monthly totals, which
gives an absolute news-attention series comparable across brands.

Same shape as the other fetchers:
    fetch(query, start, end) -> list[(month_timestamp, article_count)]
    monthly_total(query, start, end) -> int
Disk-cache-then-HTTP, polite throttle with jitter, back-off on 429/5xx. Every
raw response is cached so re-runs never re-fetch.

Note on noise: short ambiguous brand names ("Next", "On", "Gap") pull unrelated
news. GDELT is therefore treated as one signal among several, with per-entity
eligibility flags downstream — never as ground truth on its own.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import httpx

from .wikidata import USER_AGENT

GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _to_dt(ts: str) -> datetime | None:
    """Parse GDELT timeline timestamps: '20250801T000000Z' or ISO variants."""
    ts = ts.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None


class GdeltClient:
    def __init__(self, cache_dir: Path, min_interval: float = 5.0,
                 jitter: float = 2.0, max_retries: int = 4):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._min_interval = min_interval
        self._jitter = jitter
        self._max_retries = max_retries
        self._last_call = 0.0
        self._client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60.0)

    def _throttle(self) -> None:
        # Stagger requests: a base interval plus random jitter so bursts never
        # look mechanical to GDELT's rate limiter.
        gap = self._min_interval + random.random() * self._jitter
        wait = gap - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def _get(self, params: dict, cache_key: str, cache_only: bool = False) -> dict | None:
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        if cache_only:
            return None            # scoring pass: never hit the network

        for attempt in range(self._max_retries):
            self._throttle()
            resp = self._client.get(GDELT_API, params=params)
            self._last_call = time.monotonic()

            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                back = float(retry_after) if (retry_after or "").isdigit() else 15 * (attempt + 1)
                time.sleep(back)
                continue
            resp.raise_for_status()
            # GDELT sometimes returns an HTML/plain error (e.g. rate note) with a
            # 200; guard the JSON parse and treat a non-JSON body as empty.
            text = resp.text.strip()
            if not text or not text.startswith("{"):
                data: dict = {"timeline": []}
            else:
                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    data = {"timeline": []}
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        # Persistent throttle: skip this brand this cycle rather than crash the
        # whole run. Nothing is cached, so a later night retries it.
        print(f"    [gdelt] gave up (throttled) on {cache_key}", flush=True)
        return None

    def fetch(self, query: str, start: str, end: str, cache_only: bool = False) -> list[tuple[str, int]]:
        """Monthly raw article counts for `query` over [start, end] (YYYYMMDD).

        Returns [(YYYY-MM-01, count)] sorted by month. Missing months are absent
        (a real zero-signal), never fabricated.
        """
        phrase = f'"{query}"' if not query.startswith('"') else query
        params = {
            "query": phrase,
            "mode": "timelinevolraw",
            "format": "json",
            "startdatetime": f"{start}000000",
            "enddatetime": f"{end}000000",
        }
        digest = hashlib.sha256(f"{phrase}|{start}|{end}".encode("utf-8")).hexdigest()[:16]
        slug = "".join(c for c in query if c.isalnum())[:40]
        data = self._get(params, f"{slug}_{start}_{end}_{digest}", cache_only=cache_only)
        if not data:
            return []

        monthly: dict[str, int] = defaultdict(int)
        for series in data.get("timeline", []):
            for point in series.get("data", []):
                dt = _to_dt(str(point.get("date", "")))
                if dt is None:
                    continue
                val = point.get("value", 0) or 0
                monthly[f"{dt.year:04d}-{dt.month:02d}-01"] += int(round(val))
        return sorted(monthly.items())

    def monthly_total(self, query: str, start: str, end: str, cache_only: bool = False) -> int | None:
        """Total matching articles over the window (a scalar attention level).

        Returns None when cache_only and the window is not cached (ineligible),
        distinct from 0 (queried, genuinely no coverage).
        """
        series = self.fetch(query, start, end, cache_only=cache_only)
        if cache_only and not series and not self._is_cached(query, start, end):
            return None
        return sum(v for _, v in series)

    def _is_cached(self, query: str, start: str, end: str) -> bool:
        phrase = f'"{query}"' if not query.startswith('"') else query
        digest = hashlib.sha256(f"{phrase}|{start}|{end}".encode("utf-8")).hexdigest()[:16]
        slug = "".join(c for c in query if c.isalnum())[:40]
        return (self.cache_dir / f"{slug}_{start}_{end}_{digest}.json").exists()

    def close(self) -> None:
        self._client.close()
