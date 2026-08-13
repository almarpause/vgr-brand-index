"""Build the VGR Brand Index universe from Wikidata.

Instead of a hand-typed brand list (which would risk inventing brands or wrong
Q-IDs), the universe is *queried* from Wikidata: every candidate arrives with a
real Q-ID already attached and its Wikipedia sitelink count for free. Global
groups are naturally decomposed — each banner (Zara, Bershka, Pull&Bear …) is
its own Wikidata item, which is exactly the VGR-50 criterion.

Recall comes from a union of the productive Wikidata roots (chosen empirically
by counting how many business entities hang off each):

  instance of (P31/P279*)   fashion brand (Q1618899), fashion house (Q1941779)
  industry    (P452/P279*)  fashion (Q12684), clothing (Q11828862),
                            shoe (Q5915560), sporting goods (Q768186),
                            sportswear (Q645292), luxury goods (Q949715)

`textile industry` (5,250 hits: fabric mills, dyers) and the P31 product classes
(`sporting goods`, `footwear` — individual equipment, not brands) are excluded
as noise.

Raw SPARQL responses are cached to disk so re-runs never re-hit the endpoint.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from .wikidata import USER_AGENT

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

# (property, root Q-ID, human label) — kept explicit for auditability.
INSTANCE_ROOTS = [
    ("Q1618899", "fashion brand"),
    ("Q1941779", "fashion house"),
    ("Q76213285", "clothing store chain"),   # catches Lululemon & apparel chains
]

# Brands Wikidata classifies only as generic "company / retail" (so no root
# catches them) but that plainly belong in a fashion attention index. Verified
# Q-IDs, force-included. Extend as the monthly review surfaces more.
EXTRA_QIDS = [
    "Q6702957",    # Lululemon Athletica
    "Q123700068",  # Alo Yoga
    "Q56246099",   # Gymshark
    "Q16992933",   # Fabletics
]
INDUSTRY_ROOTS = [
    ("Q12684", "fashion"),
    ("Q11828862", "clothing industry"),
    ("Q5915560", "shoe industry"),
    ("Q768186", "sporting goods"),
    ("Q645292", "sportswear"),
    ("Q949715", "luxury goods"),
]

# Broad industry roots that also catch non-fashion companies (grocery,
# electronics), so their rows are kept only when the brand's own description
# reads as apparel/fashion/footwear/sport/luxury. This is what catches the DTC
# and athleisure brands Wikidata files only as generic "retail".
KEYWORD_INDUSTRY_ROOTS = [
    ("Q126793", "retail (apparel-filtered)"),
]
FASHION_DESC_REGEX = (
    "clothing|fashion|apparel|footwear|sportswear|shoe|athletic|luxury|activewear|"
    "streetwear|lingerie|denim|jeans|sneaker|handbag|couture|swimwear|knitwear|"
    "outerwear|leather goods|eyewear|watch|hosiery|menswear|womenswear|boutique"
)
# Retail matches that are plainly not a fashion brand, dropped from the broad root.
_EXCLUDE_DESC = re.compile(
    r"\b(toy|grocery|supermarket|electronics|furniture|hardware|pharmac|drugstore|"
    r"bookshop|bookstore|automotive|appliance|convenience store|pet |garden|DIY)\b",
    re.IGNORECASE,
)


@dataclass
class UniverseItem:
    qid: str
    label: str
    description: str
    sitelinks: int
    en_title: str  # "" if the brand has no English Wikipedia article


def build_root_query(prop: str, root_qid: str, keyword_filter: bool = False) -> str:
    """One root at a time — far lighter on the query service than a big UNION,
    so it does not time out or 503. Results are merged (de-duped) in Python.

    With keyword_filter, only items whose English description reads as fashion/
    apparel are returned (used for the broad `retail` root)."""
    kw = ""
    if keyword_filter:
        kw = (f'?item schema:description ?dd . FILTER(LANG(?dd)="en") '
              f'FILTER(REGEX(?dd, "{FASHION_DESC_REGEX}", "i"))')
    return f"""
SELECT ?item ?itemLabel ?itemDescription ?sitelinks ?enTitle WHERE {{
    ?item wdt:{prop}/wdt:P279* wd:{root_qid} .
    ?item wikibase:sitelinks ?sitelinks .
    {kw}
    OPTIONAL {{
        ?art schema:about ?item ;
             schema:isPartOf <https://en.wikipedia.org/> ;
             schema:name ?enTitle .
    }}
    SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""


def all_root_queries() -> list[tuple[str, str, str, bool]]:
    """(property, root_qid, label, keyword_filter) for every root."""
    queries = [("P31", qid, lbl, False) for qid, lbl in INSTANCE_ROOTS]
    queries += [("P452", qid, lbl, False) for qid, lbl in INDUSTRY_ROOTS]
    queries += [("P452", qid, lbl, True) for qid, lbl in KEYWORD_INDUSTRY_ROOTS]
    return queries


class SparqlClient:
    def __init__(self, cache_dir: Path, max_retries: int = 4):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
            timeout=180.0,
        )

    def query(self, sparql: str) -> list[dict]:
        digest = hashlib.sha256(sparql.encode("utf-8")).hexdigest()[:16]
        cache_file = self.cache_dir / f"sparql_{digest}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return data["results"]["bindings"]

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                # POST tolerates long queries better than GET.
                resp = self._client.post(
                    SPARQL_ENDPOINT, data={"query": sparql, "format": "json"}
                )
                resp.raise_for_status()
                data = resp.json()
                cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                return data["results"]["bindings"]
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                # 503/timeout from WDQS is common under load — back off and retry.
                wait = 3 * (attempt + 1)
                time.sleep(wait)
        raise RuntimeError(f"SPARQL query failed after {self.max_retries} retries") from last_exc

    def close(self) -> None:
        self._client.close()


# The root concepts themselves (e.g. "fashion" Q12684) can match their own
# P279* chain and must never appear as brands.
_ROOT_QIDS = (frozenset(q for q, _ in INSTANCE_ROOTS)
              | frozenset(q for q, _ in INDUSTRY_ROOTS)
              | frozenset(q for q, _ in KEYWORD_INDUSTRY_ROOTS))


def build_values_query(qids: list[str]) -> str:
    """Fetch specific Q-IDs by VALUES — used for the force-included extras."""
    values = " ".join(f"wd:{q}" for q in qids)
    return f"""
SELECT ?item ?itemLabel ?itemDescription ?sitelinks ?enTitle WHERE {{
    VALUES ?item {{ {values} }}
    ?item wikibase:sitelinks ?sitelinks .
    OPTIONAL {{
        ?art schema:about ?item ;
             schema:isPartOf <https://en.wikipedia.org/> ;
             schema:name ?enTitle .
    }}
    SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}
"""


def _row_to_item(row: dict) -> tuple[str, UniverseItem]:
    qid = row["item"]["value"].rsplit("/", 1)[-1]
    return qid, UniverseItem(
        qid=qid,
        label=row.get("itemLabel", {}).get("value", ""),
        description=row.get("itemDescription", {}).get("value", ""),
        sitelinks=int(row.get("sitelinks", {}).get("value", 0)),
        en_title=row.get("enTitle", {}).get("value", ""),
    )


def fetch_universe(client: SparqlClient, verbose: bool = False) -> list[UniverseItem]:
    items: dict[str, UniverseItem] = {}
    for prop, root_qid, label, kw_filter in all_root_queries():
        rows = client.query(build_root_query(prop, root_qid, keyword_filter=kw_filter))
        added = 0
        for row in rows:
            qid, item = _row_to_item(row)
            if qid in items or qid in _ROOT_QIDS:
                continue
            # The broad retail root can still catch toy/grocery/etc. chains that
            # happen to mention a garment; drop those by description.
            if kw_filter and _EXCLUDE_DESC.search(item.description or ""):
                continue
            items[qid] = item
            added += 1
        if verbose:
            print(f"  {prop:<5} {root_qid:<11} {label:<18} rows={len(rows):>5}  new={added:>5}  total={len(items)}")

    # Force-include the curated extras (mis-classified by Wikidata).
    if EXTRA_QIDS:
        extra_rows = client.query(build_values_query(EXTRA_QIDS))
        added = 0
        for row in extra_rows:
            qid, item = _row_to_item(row)
            if qid not in items:
                items[qid] = item
                added += 1
        if verbose:
            print(f"  EXTRA {'(curated)':<11} {'force-include':<18} rows={len(extra_rows):>5}  new={added:>5}  total={len(items)}")
    return list(items.values())
