"""Wikidata entity resolution for the VGR Brand Index.

Every brand is keyed on its Wikidata Q-ID, never on an article title — titles
change silently, Q-IDs don't. One Q-ID resolves to the correct article in every
language edition and carries free metadata for later tier work.

This module talks to two public, keyless Wikidata endpoints:

  * wbsearchentities — fuzzy label search, returns candidate Q-IDs + descriptions
  * wbgetentities    — full entity fetch (batched), used for per-language sitelinks

Selection never trusts the first search hit. It enriches the top candidates
with their sitelinks and, walking the search's own relevance order, picks the
first candidate that (a) reads as a fashion/retail entity and (b) actually has
an English Wikipedia article — the en pageview series is the index backbone, so
a candidate without one is close to useless.

Raw JSON responses are cached to disk so re-runs never re-hit the API.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# Wikimedia rate-limits anonymous clients hard and asks for a descriptive
# User-Agent with a contact address. See:
# https://meta.wikimedia.org/wiki/User-Agent_policy
USER_AGENT = "VGR-Brand-Index/0.1 (https://vgr.example; almarpau@gmail.com)"

# Languages we track. Order matters — it fixes column order in the CSV.
LANGUAGES: list[str] = ["en", "es", "fr", "it", "de", "ja", "zh"]

# Keywords that mark a Wikidata description as a fashion / retail company. Used
# both to score search candidates and to flag rows whose match looks off.
FASHION_KEYWORDS: tuple[str, ...] = (
    "fashion",
    "clothing",
    "apparel",
    "retail",
    "retailer",
    "luxury",
    "footwear",
    "shoe",
    "sportswear",
    "brand",
    "label",
    "couture",
    "garment",
    "textile",
    "leather",
    "manufacturer",
    "company",
    "corporation",
    "store",
    "designer",
    "streetwear",
    "fashion house",
    "goods",
    "marketplace",
    "e-commerce",
)


def _wiki_key(lang: str) -> str:
    """enwiki, eswiki, ... — the sitelink key Wikidata uses per language."""
    return f"{lang}wiki"


# Sitelink site keys that end in 'wiki' but are NOT Wikipedia language editions.
_NON_WIKIPEDIA_STEMS = {
    "commons", "species", "meta", "wikidata", "mediawiki", "sources",
    "foundation", "incubator", "wikimania", "outreach", "test", "test2",
    "login", "beta", "quote", "voyage",
}
_NON_WIKIPEDIA_MARKERS = (
    "wikisource", "wikiquote", "wikibooks", "wiktionary",
    "wikinews", "wikiversity", "wikivoyage", "wikimedia",
)


def wikipedia_edition(site: str) -> str | None:
    """Map a Wikidata sitelink key to a pageviews project language code, or None
    if the sitelink is not a Wikipedia language edition.

    'enwiki' -> 'en', 'zh_yuewiki' -> 'zh-yue', 'commonswiki' -> None.
    """
    if not site.endswith("wiki"):
        return None
    if any(m in site for m in _NON_WIKIPEDIA_MARKERS):
        return None
    stem = site[:-4]
    if stem in _NON_WIKIPEDIA_STEMS or not stem:
        return None
    return stem.replace("_", "-")


@dataclass
class Candidate:
    qid: str
    label: str
    description: str
    rank: int  # position in the search results (0 = top hit)
    titles: dict[str, str] = field(default_factory=dict)  # filled by enrich()
    enriched: bool = False

    def fashion_score(self) -> int:
        """How many fashion/retail keywords the description hits."""
        desc = self.description.lower()
        return sum(1 for kw in FASHION_KEYWORDS if kw in desc)

    def matches(self, expect: list[str]) -> bool:
        """Whether this candidate reads as the right (fashion) sense.

        With `expect` keywords, require one of them in the description; without,
        require any generic fashion/retail keyword.
        """
        desc = self.description.lower()
        if expect:
            return any(e.lower() in desc for e in expect)
        return self.fashion_score() >= 1

    @property
    def has_en(self) -> bool:
        return bool(self.titles.get("en"))


@dataclass
class Resolution:
    """The outcome of resolving one brand — one row of the report CSV."""

    name: str
    tier: str
    search_term: str
    qid: str | None = None
    label: str = ""
    description: str = ""
    titles: dict[str, str] = field(default_factory=dict)
    flag: str = ""
    note: str = ""
    candidates: list[Candidate] = field(default_factory=list)


class WikidataClient:
    """Thin cached wrapper over the Wikidata action API."""

    def __init__(self, cache_dir: Path, min_interval: float = 0.2):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._min_interval = min_interval
        self._last_call = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )

    # -- low level -----------------------------------------------------------

    def _cache_path(self, params: dict) -> Path:
        key = json.dumps(params, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{params.get('action', 'call')}_{digest}.json"

    def _get(self, params: dict) -> dict:
        params = {**params, "format": "json"}
        cache_file = self._cache_path(params)
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))

        # polite throttle between live calls
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

        resp = self._client.get(WIKIDATA_API, params=params)
        self._last_call = time.monotonic()
        resp.raise_for_status()
        data = resp.json()
        cache_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8"
        )
        return data

    # -- high level ----------------------------------------------------------

    def search(self, term: str, limit: int = 20) -> list[Candidate]:
        data = self._get(
            {
                "action": "wbsearchentities",
                "search": term,
                "language": "en",
                "uselang": "en",
                "type": "item",
                "limit": limit,
            }
        )
        out: list[Candidate] = []
        for rank, hit in enumerate(data.get("search", [])):
            out.append(
                Candidate(
                    qid=hit.get("id", ""),
                    label=hit.get("label", ""),
                    description=hit.get("description", ""),
                    rank=rank,
                )
            )
        return out

    def entities(self, qids: list[str]) -> dict[str, dict]:
        """Batch fetch labels/descriptions/sitelinks for up to 50 Q-IDs."""
        if not qids:
            return {}
        data = self._get(
            {
                "action": "wbgetentities",
                "ids": "|".join(qids),
                "props": "sitelinks|labels|descriptions",
                "languages": "|".join(LANGUAGES),
                "sitefilter": "|".join(_wiki_key(l) for l in LANGUAGES),
            }
        )
        return data.get("entities", {})

    def wikipedia_sitelinks(self, qids: list[str]) -> dict[str, dict[str, str]]:
        """For each Q-ID, {pageviews-lang-code: article title} across EVERY
        Wikipedia language edition (no tracked-language filter)."""
        out: dict[str, dict[str, str]] = {}
        for start in range(0, len(qids), 50):
            batch = qids[start : start + 50]
            data = self._get(
                {
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "sitelinks",
                }
            )
            for qid, entity in data.get("entities", {}).items():
                editions: dict[str, str] = {}
                for site, link in entity.get("sitelinks", {}).items():
                    lang = wikipedia_edition(site)
                    if lang:
                        editions[lang] = link.get("title", "")
                out[qid] = editions
        return out

    def enrich(self, candidates: list[Candidate]) -> None:
        """Fill each candidate's per-language titles (and sharpen its en label/
        description) from a single batched wbgetentities call."""
        qids = [c.qid for c in candidates if c.qid]
        entities = self.entities(qids)
        for c in candidates:
            entity = entities.get(c.qid)
            if not entity:
                c.enriched = True
                continue
            en_label = entity.get("labels", {}).get("en", {}).get("value", "")
            en_desc = entity.get("descriptions", {}).get("en", {}).get("value", "")
            if en_label:
                c.label = en_label
            if en_desc:
                c.description = en_desc
            sitelinks = entity.get("sitelinks", {})
            titles: dict[str, str] = {}
            for lang in LANGUAGES:
                link = sitelinks.get(_wiki_key(lang))
                if link:
                    titles[lang] = link.get("title", "")
            c.titles = titles
            c.enriched = True

    def close(self) -> None:
        self._client.close()


# Brands the spec flags as resolving wrongly on the first search hit. These are
# always sent to manual review even when the automatic match looks confident.
ALWAYS_REVIEW: frozenset[str] = frozenset(
    {"On", "Celine", "Loewe", "Next", "Supreme", "The Row", "Mango", "Arket"}
)


def choose(candidates: list[Candidate], expect: list[str]) -> tuple[Candidate | None, str]:
    """Pick the best candidate from an *enriched* candidate list.

    Preference order, all walking the search's own relevance ranking:
      1. matches the fashion sense AND has an English article  -> clean
      2. matches the fashion sense but no English article       -> NO_EN_ARTICLE
      3. has an English article but sense is uncertain          -> flagged
      4. anything at all (top hit)                              -> flagged
    """
    if not candidates:
        return None, "NO_CANDIDATES"

    ordered = sorted(candidates, key=lambda c: c.rank)

    # 1. right sense + en article
    for c in ordered:
        if c.matches(expect) and c.has_en:
            return c, ""

    # 2. right sense, no en article
    for c in ordered:
        if c.matches(expect):
            return c, "NO_EN_ARTICLE"

    # 3. en article but sense uncertain (expect keywords never matched)
    flag = "EXPECT_NOT_MATCHED" if expect else "NO_FASHION_KEYWORD"
    for c in ordered:
        if c.has_en:
            return c, flag

    # 4. nothing clean at all — return the top hit, flagged loudly
    return ordered[0], flag + ";NO_EN_ARTICLE"
