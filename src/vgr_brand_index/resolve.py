"""Phase 1 entrypoint — resolve every brand in brands.yaml to a Wikidata Q-ID
and per-language article titles, then write a resolution report for review.

Run from the project root:

    uv run python -m vgr_brand_index.resolve

Outputs:
    output/resolution.csv   one row per brand, for you to eyeball at the gate

Nothing downstream should run until the CSV has been reviewed and confirmed.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml

from .wikidata import (
    ALWAYS_REVIEW,
    LANGUAGES,
    Resolution,
    WikidataClient,
    choose,
)

ROOT = Path(__file__).resolve().parents[2]
BRANDS_FILE = ROOT / "brands.yaml"
CACHE_DIR = ROOT / "cache" / "wikidata"
OUTPUT_DIR = ROOT / "output"


def load_brands(path: Path) -> list[dict]:
    """Flatten brands.yaml into a list of brand dicts."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    brands: list[dict] = []
    for tier, entries in data.get("tiers", {}).items():
        for entry in entries:
            if isinstance(entry, str):
                brands.append(
                    {
                        "name": entry,
                        "tier": tier,
                        "search": entry,
                        "expect": [],
                        "qid": None,
                        "wikipedia": None,
                        "note": "",
                    }
                )
            else:
                name = str(entry["name"])
                brands.append(
                    {
                        "name": name,
                        "tier": tier,
                        "search": str(entry.get("search", name)),
                        "expect": entry.get("expect", []),
                        "qid": entry.get("qid"),
                        "wikipedia": entry.get("wikipedia"),
                        "note": entry.get("note", ""),
                    }
                )
    return brands


def lang_flag(titles: dict[str, str]) -> str:
    """Classify Wikipedia coverage from the resolved per-language titles."""
    if not titles:
        return "NO_WIKIPEDIA"       # a Q-ID exists but no article in any tracked lang
    if "en" not in titles:
        return "NO_EN_ARTICLE"      # non-English editions only (still usable)
    return ""


def _combine(*flags: str) -> str:
    """Join non-empty flag tokens with ';'."""
    return ";".join(f for f in flags if f)


def resolve_brand(client: WikidataClient, brand: dict) -> Resolution:
    name = str(brand["name"])
    res = Resolution(name=name, tier=brand["tier"], search_term=str(brand["search"]))
    res.note = brand.get("note", "")

    # Path 0: brand explicitly marked as having no Wikipedia entity. Keep it in
    # the index (GDELT / Trends can still track the string) but resolve nothing.
    if brand.get("wikipedia") == "none":
        res.flag = "NO_WIKIPEDIA_ENTITY"
        return res

    # Path A: a Q-ID was pinned in brands.yaml — trust it, just fetch titles.
    if brand.get("qid"):
        res.qid = str(brand["qid"])
        entity = client.entities([res.qid]).get(res.qid, {})
        res.label = entity.get("labels", {}).get("en", {}).get("value", "")
        res.description = entity.get("descriptions", {}).get("en", {}).get("value", "")
        sitelinks = entity.get("sitelinks", {})
        res.titles = {
            lang: sitelinks[f"{lang}wiki"]["title"]
            for lang in LANGUAGES
            if f"{lang}wiki" in sitelinks
        }
        res.flag = _combine("PINNED", lang_flag(res.titles))
        return res

    # Path B: resolve from scratch. Search, enrich the candidates with their
    # sitelinks in one batched call, then choose by relevance + en-article.
    candidates = client.search(brand["search"])
    client.enrich(candidates)
    res.candidates = candidates
    best, flag = choose(candidates, brand["expect"])
    if best is None:
        res.flag = flag
        return res

    res.qid = best.qid
    res.label = best.label
    res.description = best.description
    res.titles = dict(best.titles)

    # Brands the spec flags as ambiguous always go to manual review, even when
    # the automatic match looks confident.
    if name in ALWAYS_REVIEW and not flag:
        flag = "REVIEW_AMBIGUOUS"
    res.flag = _combine(flag, lang_flag(res.titles))

    return res


def write_csv(resolutions: list[Resolution], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        ["tier", "brand", "qid", "matched_label", "description", "flag",
         "wikipedia_langs", "note"]
        + [f"{lang}_title" for lang in LANGUAGES]
    )
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in resolutions:
            langs = ",".join(lang for lang in LANGUAGES if lang in r.titles)
            writer.writerow(
                [r.tier, r.name, r.qid or "", r.label, r.description, r.flag,
                 langs, r.note]
                + [r.titles.get(lang, "") for lang in LANGUAGES]
            )


def main() -> int:
    if not BRANDS_FILE.exists():
        print(f"brands.yaml not found at {BRANDS_FILE}", file=sys.stderr)
        return 1

    brands = load_brands(BRANDS_FILE)
    print(f"Loaded {len(brands)} brands from {BRANDS_FILE.name}")

    client = WikidataClient(CACHE_DIR)
    resolutions: list[Resolution] = []
    try:
        for i, brand in enumerate(brands, 1):
            res = resolve_brand(client, brand)
            flag = f"  [{res.flag}]" if res.flag else ""
            print(f"  {i:>2}/{len(brands)}  {res.name:<18} {res.qid or 'UNRESOLVED':<10} {res.label}{flag}")
            resolutions.append(res)
    finally:
        client.close()

    out_path = OUTPUT_DIR / "resolution.csv"
    write_csv(resolutions, out_path)

    def names(rs: list[Resolution]) -> str:
        return ", ".join(r.name for r in rs) or "-"

    review_tokens = ("REVIEW", "EXPECT_NOT_MATCHED", "NO_FASHION_KEYWORD", "NO_CANDIDATES")
    needs_review = [r for r in resolutions if any(t in r.flag for t in review_tokens)]
    no_entity = [r for r in resolutions if "NO_WIKIPEDIA_ENTITY" in r.flag]
    q_no_article = [r for r in resolutions if r.qid and not r.titles]
    no_en = [r for r in resolutions if r.titles and "en" not in r.titles]
    clean = [r for r in resolutions if r.qid and "en" in r.titles and r not in needs_review]

    print()
    print(f"Wrote {out_path}")
    print(f"  brands                    : {len(resolutions)}")
    print(f"  clean (Q-ID + en article) : {len(clean)}")
    print(f"  non-English article only  : {len(no_en):>2}  ({names(no_en)})")
    print(f"  Q-ID but no article       : {len(q_no_article):>2}  ({names(q_no_article)})")
    print(f"  no Wikipedia entity       : {len(no_entity):>2}  ({names(no_entity)})")
    print(f"  still needs manual review : {len(needs_review):>2}  ({names(needs_review)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
