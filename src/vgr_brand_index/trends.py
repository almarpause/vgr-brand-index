"""Google Trends search-interest fetcher — attention source #3 (best-effort).

Trends is an *unofficial* endpoint reached through `pytrends`: it rate-limits and
blocks readily, and its 0-100 scale is relative to each query's own maximum, so
raw values are not comparable across queries. Two design consequences:

  * Anchor chaining — every batch of up to four brands is queried together with
    one constant reference term; each brand's score is expressed as a ratio to
    the anchor's mean, which puts all brands on one absolute (anchor = 100) scale.

  * Graceful degradation — pytrends may be missing or blocked. Import is lazy and
    every failure is swallowed into a per-entity *ineligible* result: the brand
    simply carries no Trends signal and the composite renormalises over its other
    sources. The index never blocks on Trends and never fabricates a value.

Staggering (few batches per night) lives in the caller, not here.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path

DEFAULT_ANCHOR = "Adidas"          # globally known, mid-high — rarely saturates
DEFAULT_TIMEFRAME = "today 12-m"
BATCH_BRANDS = 4                    # +1 anchor = the Trends max of 5 terms


class TrendsUnavailable(Exception):
    """Raised internally when pytrends is missing or a batch keeps failing."""


class TrendsClient:
    def __init__(
        self,
        cache_dir: Path,
        anchor: str = DEFAULT_ANCHOR,
        timeframe: str = DEFAULT_TIMEFRAME,
        geo: str = "",
        min_interval: float = 4.0,
        jitter: float = 3.0,
        max_retries: int = 3,
    ):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.anchor = anchor
        self.timeframe = timeframe
        self.geo = geo
        self._min_interval = min_interval
        self._jitter = jitter
        self._max_retries = max_retries
        self._last_call = 0.0
        self._pt = None            # lazy TrendReq

    # -- pytrends plumbing ---------------------------------------------------

    def _trendreq(self):
        if self._pt is None:
            try:
                from pytrends.request import TrendReq
            except Exception as exc:  # not installed / import error
                raise TrendsUnavailable(f"pytrends unavailable: {exc}") from exc
            self._pt = TrendReq(hl="en-US", tz=0, timeout=(10, 30))
        return self._pt

    def _throttle(self) -> None:
        gap = self._min_interval + random.random() * self._jitter
        wait = gap - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def _cache_path(self, terms: list[str]) -> Path:
        key = "|".join(terms) + f"|{self.timeframe}|{self.geo}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        slug = "".join(c for c in "_".join(terms) if c.isalnum() or c == "_")[:48]
        return self.cache_dir / f"{slug}_{digest}.json"

    # -- one batch -----------------------------------------------------------

    def _fetch_batch(self, terms: list[str], cache_only: bool = False) -> dict[str, float]:
        """Mean interest-over-time per term for one batch (anchor first).

        Cached. Raises TrendsUnavailable if pytrends errors after retries (or if
        cache_only and the batch is not cached); a cached empty dict means
        'queried, genuinely no data'.
        """
        cache_file = self._cache_path(terms)
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        if cache_only:
            raise TrendsUnavailable("not cached (cache_only)")

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            self._throttle()
            try:
                pt = self._trendreq()
                pt.build_payload(terms, timeframe=self.timeframe, geo=self.geo)
                df = pt.interest_over_time()
                self._last_call = time.monotonic()
                means: dict[str, float] = {}
                if df is not None and not df.empty:
                    for t in terms:
                        if t in df.columns:
                            means[t] = float(df[t].mean())
                cache_file.write_text(json.dumps(means, ensure_ascii=False), encoding="utf-8")
                return means
            except TrendsUnavailable:
                raise
            except Exception as exc:  # 429 / network / parse — back off and retry
                self._last_call = time.monotonic()
                last_exc = exc
                time.sleep(8 * (attempt + 1) + random.random() * 4)
        raise TrendsUnavailable(f"batch failed after {self._max_retries} retries: {last_exc}")

    # -- public: score a list of brands --------------------------------------

    def score_brands(self, terms: list[str], cache_only: bool = False) -> dict[str, float | None]:
        """Absolute (anchor = 100) search-interest score per brand term.

        A term maps to None when its batch could not be fetched (Trends
        ineligible for that brand). Anchor is prepended to every batch and its
        own score is not returned.
        """
        out: dict[str, float | None] = {}
        brand_terms = [t for t in terms if t and t != self.anchor]
        for i in range(0, len(brand_terms), BATCH_BRANDS):
            batch = brand_terms[i : i + BATCH_BRANDS]
            query = [self.anchor, *batch]
            try:
                means = self._fetch_batch(query, cache_only=cache_only)
            except TrendsUnavailable:
                for b in batch:
                    out[b] = None            # ineligible — renormalised away
                continue
            anchor_mean = means.get(self.anchor, 0.0)
            for b in batch:
                bv = means.get(b, 0.0)
                if anchor_mean and anchor_mean > 0:
                    out[b] = round(bv / anchor_mean * 100.0, 2)
                elif bv > 0:
                    # anchor flat but brand has signal — keep raw as a floor
                    out[b] = round(bv, 2)
                else:
                    out[b] = 0.0
        return out

    def close(self) -> None:
        self._pt = None
