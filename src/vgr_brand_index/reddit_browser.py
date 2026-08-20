"""Reddit consumer-buzz via the public search page (headless browser, no login).

Reddit's JSON API is 403'd for automation and its OAuth app is a pain to create,
but the **public search website** renders fine in a real browser. So this loads
`reddit.com/search` in headless Chromium (which runs the page's JS like a human)
and reads the comment counts off the top posts — a discriminating buzz signal
(Nike ≫ Zara ≫ niche) that needs no credentials and no authorisation.

Signal = sum of comment counts on the most-commented posts for the brand,
trailing year. Same cache files as the OAuth client (reddit.cache_file_for), so
scoring reads whichever populated them.

    uv run python -m vgr_brand_index.reddit_browser --test Zara
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from urllib.parse import quote

from .config import ROOT
from .reddit import cache_file_for

CACHE = ROOT / "cache" / "reddit"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Sum the "N comments" counts rendered on the search results page (k/m aware).
_JS = r"""()=>{
  const t=document.body.innerText;
  const c=[...t.matchAll(/([\d.,]+)\s*([km]?)\s+comment/gi)].map(m=>{
    let n=parseFloat(m[1].replace(/,/g,'')); const s=(m[2]||'').toLowerCase();
    if(s==='k')n*=1000; if(s==='m')n*=1e6; return Math.round(n);});
  return {posts:document.querySelectorAll('a[href*="/comments/"]').length,
          comments:c.reduce((a,b)=>a+b,0)};
}"""


class RedditBrowserClient:
    def __init__(self, cache_dir: Path = CACHE, timeframe: str = "year",
                 min_interval: float = 3.0, jitter: float = 2.5):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeframe = timeframe
        self._min_interval = min_interval
        self._jitter = jitter
        self._last = 0.0
        self._pw = None
        self._ctx = None
        self._page = None

    def _open(self):
        if self._page is not None:
            return self._page
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch(headless=True).new_context(
            user_agent=_UA, viewport={"width": 1280, "height": 900})
        self._page = self._ctx.new_page()
        return self._page

    def close(self) -> None:
        for obj, meth in ((self._ctx, "close"), (self._pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, meth)()
            except Exception:
                pass
        self._ctx = self._pw = self._page = None

    def _throttle(self) -> None:
        gap = self._min_interval + random.random() * self._jitter
        wait = gap - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)

    def _search(self, brand: str) -> dict | None:
        page = self._open()
        url = (f"https://www.reddit.com/search/?q=%22{quote(brand)}%22"
               f"&type=posts&sort=comments&t={self.timeframe}")
        self._throttle()
        try:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            try:
                page.wait_for_selector('a[href*="/comments/"]', timeout=12000)
            except Exception:
                pass  # genuinely no results -> comments 0
            time.sleep(1.5)
            rec = page.evaluate(_JS)
        except Exception:
            self._last = time.monotonic()
            return None
        self._last = time.monotonic()
        return rec

    def fetch(self, brand: str, cache_only: bool = False) -> int | None:
        cache_file = cache_file_for(self.cache_dir, brand, self.timeframe)
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8")).get("comments")
        if cache_only:
            return None
        rec = self._search(brand)
        if rec is None:
            return None
        cache_file.write_text(json.dumps(rec), encoding="utf-8")
        return rec["comments"]

    def fetch_many(self, brands: list[str], verbose: bool = True) -> int:
        got = 0
        for n, b in enumerate(brands, 1):
            cache_file = cache_file_for(self.cache_dir, b, self.timeframe)
            if cache_file.exists():
                got += 1
                continue
            rec = self._search(b)
            if rec is not None:
                cache_file.write_text(json.dumps(rec), encoding="utf-8")
                got += 1
            if verbose and (n % 25 == 0 or n == len(brands)):
                print(f"    reddit(browser) {n}/{len(brands)}  got={got}", flush=True)
        return got


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Reddit-via-browser buzz (no login).")
    ap.add_argument("--test", metavar="BRAND", default="Zara")
    args = ap.parse_args(argv)
    c = RedditBrowserClient()
    print(f"{args.test}: comments={c.fetch(args.test)}")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
