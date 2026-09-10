"""Google Trends search-interest fetcher — attention source #3 (best-effort).

Trends is an *unofficial* endpoint reached through `pytrends`. Three hard problems
are handled here:

  * Comparability — raw values are relative to each query's own maximum, so every
    batch of up to four brands is queried together with a constant anchor and
    rescaled to the anchor (anchor = 100), putting all brands on one scale.

  * Disambiguation & relevance — a raw brand string is a bad search term: "HEAD"
    matches the body part, "On" the preposition, and "Lululemon Athletica" is not
    what anyone types. So each brand is first resolved to a Google **topic entity**
    (a `/m/...` mid via the suggestions API), preferring a company/brand topic.
    Querying the topic gives disambiguated, relevant interest. Falls back to a
    cleaned keyword when no topic is found.

  * Fragility — pytrends may be missing or blocked. Every failure is swallowed
    into a per-brand *ineligible* result; the index never blocks and never
    fabricates a value.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from pathlib import Path

DEFAULT_ANCHOR = "Adidas"
DEFAULT_TIMEFRAME = "today 12-m"
BATCH_BRANDS = 4

# Suggestion types that mark a topic as the right (brand/company) sense.
_BRAND_TYPES = ("compan", "brand", "retail", "clothing", "fashion", "footwear",
                "apparel", "label", "manufacturer", "house", "corporation",
                "business", "enterprise")
# Corporate suffixes stripped for the keyword fallback (when no topic is found).
_SUFFIX_RE = re.compile(
    r"\s*(,?\s*(inc\.?|incorporated|corp\.?|corporation|co\.?|company|group|holdings?|"
    r"ltd\.?|limited|plc|s\.?a\.?|s\.?e\.?|a\.?g\.?|b\.?v\.?|n\.?v\.?|athletica|"
    r"international|brands?))+\s*$",
    re.IGNORECASE,
)


def clean_term(label: str) -> str:
    t = _SUFFIX_RE.sub("", label).strip()
    return t or label


class TrendsUnavailable(Exception):
    pass


class TrendsClient:
    def __init__(self, cache_dir: Path, anchor: str = DEFAULT_ANCHOR,
                 timeframe: str = DEFAULT_TIMEFRAME, geo: str = "",
                 min_interval: float = 4.0, jitter: float = 3.0, max_retries: int = 3,
                 gprop: str = ""):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.anchor = anchor
        self.timeframe = timeframe
        # Google property the interest is measured on: "" = web search (the default
        # index signal), "news" = Google News search, also "images"/"youtube"/"froogle".
        # Anchor-chaining, basket rescale and resolver are property-agnostic, so the
        # exact same method yields a comparable level for any property.
        self.gprop = gprop
        # Worldwide is the index's fixed geography (geo="" == all countries). A
        # non-empty geo would make levels country-specific and non-comparable with
        # the stored basket, so flag it loudly rather than silently drift.
        if geo:
            print(f"[trends] WARNING: geo={geo!r} is NOT worldwide; index expects geo=''")
        self.geo = geo
        self._min_interval = min_interval
        self._jitter = jitter
        self._max_retries = max_retries
        self._last_call = 0.0
        self._pt = None
        self._qmap_path = self.cache_dir / "_query_map.json"
        self._qmap: dict[str, str] = (
            json.loads(self._qmap_path.read_text(encoding="utf-8")) if self._qmap_path.exists() else {}
        )

    # -- plumbing ------------------------------------------------------------

    def _trendreq(self):
        if self._pt is None:
            try:
                from pytrends.request import TrendReq
            except Exception as exc:
                raise TrendsUnavailable(f"pytrends unavailable: {exc}") from exc
            self._pt = TrendReq(hl="en-US", tz=0, timeout=(10, 30))
        return self._pt

    def _throttle(self) -> None:
        gap = self._min_interval + random.random() * self._jitter
        wait = gap - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    def _save_qmap(self) -> None:
        self._qmap_path.write_text(json.dumps(self._qmap, ensure_ascii=False), encoding="utf-8")

    # -- topic resolution ----------------------------------------------------

    def resolve_query(self, label: str, cache_only: bool = False) -> str | None:
        """Return the Trends query token for a brand: a topic mid when one exists,
        else a cleaned keyword. None when cache_only and not yet resolved.

        Disambiguation policy: when a brand name yields more than one brand/company
        topic candidate, pick the one with the largest *worldwide* search interest
        (one comparison query; Trends normalises within a batch, so candidate means
        are directly comparable). This resolves the corporate-vs-consumer split in
        favour of the entity people actually search — e.g. the "Levi's" brand topic
        over the "Levi Strauss & Co." company topic, "On" the running brand over the
        holding company. Falls back to suggestion order if the comparison fails."""
        if label in self._qmap:
            return self._qmap[label]
        if cache_only:
            return None
        token = clean_term(label)
        try:
            self._throttle()
            pt = self._trendreq()
            sugg = pt.suggestions(label) or []
            self._last_call = time.monotonic()
            # brand/company topic candidates, in suggestion order, de-duplicated
            cands, seen = [], set()
            for s in sugg:
                mid = s.get("mid")
                typ = (s.get("type") or "").lower()
                if mid and mid not in seen and any(k in typ for k in _BRAND_TYPES):
                    cands.append(mid); seen.add(mid)
            if len(cands) >= 2:
                token = self._pick_highest_traffic(cands)
            elif len(cands) == 1:
                token = cands[0]
            elif sugg:
                # no brand topic; take the first topic that isn't the raw
                # dictionary sense (skip type "Topic" with no brand words)
                first = sugg[0]
                if first.get("type") and "topic" not in first["type"].lower():
                    token = first.get("mid") or clean_term(label)
        except TrendsUnavailable:
            raise
        except Exception:
            token = clean_term(label)          # suggestions failed — keyword fallback
        self._qmap[label] = token
        self._save_qmap()
        return token

    def _pick_highest_traffic(self, mids: list[str]) -> str:
        """Among candidate topic mids, the one with the largest worldwide mean
        interest. Single cached comparison query; falls back to the first mid."""
        mids = mids[:5]                        # Trends payload cap
        try:
            means = self._fetch_batch(mids, cache_only=False)
        except Exception:
            return mids[0]
        if not means:
            return mids[0]
        return max(mids, key=lambda m: means.get(m, 0.0))

    # -- batch fetch ---------------------------------------------------------

    def _cache_path(self, tokens: list[str]) -> Path:
        # gprop is part of the key so news batches never collide with web batches.
        key = "|".join(tokens) + f"|{self.timeframe}|{self.geo}|{self.gprop}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        tag = f"{self.gprop}_" if self.gprop else ""
        return self.cache_dir / f"batch_{tag}{digest}.json"

    def _fetch_batch(self, tokens: list[str], cache_only: bool = False) -> dict[str, float]:
        """Mean interest per query token for one batch (anchor token first)."""
        cache_file = self._cache_path(tokens)
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))
        if cache_only:
            raise TrendsUnavailable("not cached (cache_only)")

        last_exc = None
        for attempt in range(self._max_retries):
            self._throttle()
            try:
                pt = self._trendreq()
                pt.build_payload(tokens, timeframe=self.timeframe, geo=self.geo, gprop=self.gprop)
                df = pt.interest_over_time()
                self._last_call = time.monotonic()
                means: dict[str, float] = {}
                if df is not None and not df.empty:
                    for t in tokens:
                        if t in df.columns:
                            means[t] = float(df[t].mean())
                cache_file.write_text(json.dumps(means, ensure_ascii=False), encoding="utf-8")
                return means
            except TrendsUnavailable:
                raise
            except Exception as exc:
                self._last_call = time.monotonic()
                last_exc = exc
                time.sleep(8 * (attempt + 1) + random.random() * 4)
        raise TrendsUnavailable(f"batch failed after {self._max_retries} retries: {last_exc}")

    # -- public --------------------------------------------------------------

    def score_brands(self, terms: list[str], cache_only: bool = False,
                     only_shard: int | None = None, n_shards: int | None = None) -> dict[str, float | None]:
        """Absolute (anchor = 100) search-interest score per brand label.

        Brands are resolved to topic entities, batched in the order given (callers
        pass a stable order, e.g. pageviews-descending). None = ineligible.
        """
        out: dict[str, float | None] = {}
        anchor_token = self.resolve_query(self.anchor, cache_only=cache_only)
        if anchor_token is None:
            anchor_token = self.anchor

        seen: set[str] = set()
        brands = [t for t in terms if t and t != self.anchor and not (t in seen or seen.add(t))]
        for bi, i in enumerate(range(0, len(brands), BATCH_BRANDS)):
            if only_shard is not None and n_shards and (bi % n_shards) != only_shard:
                continue
            batch = brands[i : i + BATCH_BRANDS]
            tokens, tok_of = [anchor_token], {}
            for b in batch:
                tk = self.resolve_query(b, cache_only=cache_only)
                if tk is None:
                    out[b] = None
                    continue
                tokens.append(tk)
                tok_of[b] = tk
            if len(tokens) < 2:
                continue
            try:
                means = self._fetch_batch(tokens, cache_only=cache_only)
            except TrendsUnavailable:
                for b in batch:
                    out.setdefault(b, None)
                continue
            anchor_mean = means.get(anchor_token, 0.0)
            for b in batch:
                if b not in tok_of:
                    continue
                bv = means.get(tok_of[b], 0.0)
                if anchor_mean > 0:
                    out[b] = round(bv / anchor_mean * 100.0, 2)
                else:
                    out[b] = round(bv, 2) if bv > 0 else 0.0
        return out

    def close(self) -> None:
        self._pt = None
