"""Wikipedia pageviews fetcher — source #1 and the index backbone.

Wraps the Wikimedia REST pageviews API (per-article, all-access, agent=user so
bot traffic is excluded). Keyless, but Wikimedia rate-limits anonymous clients
hard, so a descriptive User-Agent with a contact address is mandatory and calls
are throttled and cached.

Two uses:
  * interest ranking — trailing-12-month monthly totals (this module's helper)
  * Phase-2 signal    — daily series back to 2015 via fetch_daily()

Every raw response is cached to disk; re-runs never re-fetch.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

from .wikidata import USER_AGENT

REST_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"


def _project(lang: str) -> str:
    return f"{lang}.wikipedia.org"


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def trailing_12_month_window(today: date | None = None) -> tuple[str, str]:
    """(start, end) as YYYYMMDD covering the 12 most recent *complete* months.

    Pageview data lags slightly, so the window ends at the last day of the month
    before the current one.
    """
    today = today or date.today()
    end_month_last = _first_of_month(today) - timedelta(days=1)      # last day of prev month
    start_month_first = _first_of_month(end_month_last)
    for _ in range(11):                                             # step back 11 more months
        start_month_first = _first_of_month(start_month_first - timedelta(days=1))
    return start_month_first.strftime("%Y%m%d"), end_month_last.strftime("%Y%m%d")


class PageviewsClient:
    def __init__(self, cache_dir: Path, min_interval: float = 0.25, max_retries: int = 5):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_call = 0.0
        self._client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0)

    def _get(self, url: str, cache_key: str) -> dict | None:
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        for attempt in range(self._max_retries):
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            resp = self._client.get(url)
            self._last_call = time.monotonic()

            # 404 = the article has no pageview data for that range. A real
            # 'zero signal' answer, not an error — cache an empty result.
            if resp.status_code == 404:
                cache_file.write_text(json.dumps({"items": []}), encoding="utf-8")
                return {"items": []}
            # 429 / 5xx — Wikimedia is throttling. Honour Retry-After, else back off.
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                back = float(retry_after) if (retry_after or "").isdigit() else 2 * (attempt + 1)
                time.sleep(back)
                continue
            resp.raise_for_status()
            data = resp.json()
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        raise RuntimeError(f"pageviews API kept throttling after {self._max_retries} retries: {url}")

    def fetch(
        self, article: str, lang: str, start: str, end: str, granularity: str = "monthly"
    ) -> list[tuple[str, int]]:
        """Return [(timestamp, views)] for one article in one language."""
        # Article title -> API path: spaces to underscores, then percent-encode.
        title = quote(article.replace(" ", "_"), safe="")
        url = f"{REST_BASE}/{_project(lang)}/all-access/user/{title}/{granularity}/{start}/{end}"
        safe_title = article.replace("/", "__").replace(" ", "_")[:80]
        cache_key = f"{lang}_{granularity}_{start}_{end}_{safe_title}"
        data = self._get(url, cache_key)
        if not data:
            return []
        return [(it["timestamp"], it.get("views", 0)) for it in data.get("items", [])]

    def trailing_12mo_total(self, article: str, lang: str, window: tuple[str, str]) -> int:
        """Total user pageviews over the trailing-12-month window."""
        series = self.fetch(article, lang, window[0], window[1], granularity="monthly")
        return sum(v for _, v in series)

    def close(self) -> None:
        self._client.close()
