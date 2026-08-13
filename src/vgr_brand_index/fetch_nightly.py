"""Staggered nightly fetch — the gentle half of the pipeline.

The universe is partitioned into N shards by a hash of each brand's Q-ID. Each
night this fetches just one shard's signals (pageviews, GDELT, Trends) with
jittered throttling, so every brand refreshes roughly once a month and no
endpoint is ever hammered. Which shard runs is picked from the day of month by
default, so a plain daily schedule rotates through the whole universe.

Cache-first and resumable: anything already fetched is skipped, so a failed or
partial night simply resumes.

    uv run python -m vgr_brand_index.fetch_nightly            # today's shard
    uv run python -m vgr_brand_index.fetch_nightly --shard 3  # a specific shard
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import date

from .gdelt import GdeltClient
from .interest import CACHE
from .pageviews import PageviewsClient, trailing_12_month_window
from .signals import gather_signals
from .trends import TrendsClient
from .universe import SparqlClient, fetch_universe
from .wikidata import WikidataClient

DEFAULT_SHARDS = 28


def shard_of(qid: str, n_shards: int) -> int:
    return int(hashlib.sha256(qid.encode("utf-8")).hexdigest(), 16) % n_shards


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch one nightly shard of brand signals.")
    ap.add_argument("--shards", type=int, default=DEFAULT_SHARDS,
                    help="number of shards the universe is split into")
    ap.add_argument("--shard", type=int, default=None,
                    help="which shard to fetch (default: derived from day of month)")
    ap.add_argument("--no-trends", action="store_true", help="skip Google Trends this run")
    args = ap.parse_args(argv)

    shard = args.shard if args.shard is not None else (date.today().day - 1) % args.shards
    window = trailing_12_month_window(date.today())
    print(f"Nightly fetch — shard {shard}/{args.shards}, window {window[0]}..{window[1]}")

    sp = SparqlClient(CACHE / "sparql")
    items = fetch_universe(sp)
    sp.close()
    viable = [i for i in items if i.sitelinks > 0 and i.label]
    mine = [i for i in viable if shard_of(i.qid, args.shards) == shard]
    print(f"  universe {len(viable)} viable; this shard {len(mine)} brands")
    if not mine:
        return 0

    wd = WikidataClient(CACHE / "wikidata")
    editions = wd.wikipedia_sitelinks([i.qid for i in mine])
    wd.close()

    pv = PageviewsClient(CACHE / "pageviews")
    gdelt = GdeltClient(CACHE / "gdelt")
    trends = TrendsClient(CACHE / "trends")

    # pv + GDELT are per-brand: fetch this brand-shard. cache_only=False -> fetch.
    df = gather_signals(
        mine, editions, pv, gdelt, trends, window,
        cache_only=False, do_trends=False, verbose=True,
    )

    # Trends is anchor-batched, so it is sharded by BATCH over the whole universe
    # (globally sorted -> stable cache keys the monthly read can find), not by the
    # pv/gdelt brand-shard.
    n_trends = 0
    if not args.no_trends:
        all_labels = [i.label for i in viable]
        tscores = trends.score_brands(all_labels, cache_only=False,
                                      only_shard=shard, n_shards=args.shards)
        n_trends = sum(1 for v in tscores.values() if v is not None)
    pv.close(); gdelt.close(); trends.close()

    got = {"pv": int(df["elig_pv"].sum()), "gdelt": int(df["elig_gdelt"].sum()), "trends": n_trends}
    print(f"  fetched — pv/gdelt for {len(df)} brands, trends batch-shard: {got}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
