"""Reddit consumer-buzz fetcher — attention source #4.

Reddit is the signal pageviews miss: what people actually talk about buying. It
skews toward mass, streetwear, sneakers and athleisure over dusty luxury, which
is exactly the commercial-attention correction the index needs.

Reddit's free API requires OAuth since 2023, so this uses **application-only**
auth (client_credentials): register a "script" app at
https://www.reddit.com/prefs/apps, then provide the id/secret via env
(VBI_REDDIT_CLIENT_ID / VBI_REDDIT_CLIENT_SECRET) or config/reddit.ini. No Reddit
password or account login is needed.

Buzz is measured as the total comment volume on posts matching the brand within a
curated set of fashion subreddits (restrict_sr) over the trailing year — the
subreddit context cuts the ambiguity of names like "On" or "Gap". Missing creds
or an API error degrade gracefully to ineligible; nothing is fabricated.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from configparser import ConfigParser
from pathlib import Path

import httpx

from .config import ROOT
from .wikidata import USER_AGENT

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH = "https://oauth.reddit.com"

# Curated fashion/apparel subreddits — the search context.
FASHION_SUBS = (
    "fashion+streetwear+femalefashionadvice+malefashionadvice+frugalmalefashion+"
    "frugalfemalefashion+sneakers+luxury+handbags+Watches+findfashion+"
    "japanesestreetwear+rawdenim+goodyearwelt+PlusSizeFashion+curvyfashion+"
    "fashionwomens+mensfashion+streetwearstartup+Repsneakers"
)


class RedditUnavailable(Exception):
    pass


def load_credentials() -> tuple[str, str] | None:
    cid = os.environ.get("VBI_REDDIT_CLIENT_ID", "")
    sec = os.environ.get("VBI_REDDIT_CLIENT_SECRET", "")
    if not (cid and sec):
        ini = ROOT / "config" / "reddit.ini"
        if ini.exists():
            cp = ConfigParser()
            cp.read(ini, encoding="utf-8")
            if cp.has_section("reddit"):
                cid = cid or cp.get("reddit", "client_id", fallback="")
                sec = sec or cp.get("reddit", "client_secret", fallback="")
    return (cid, sec) if (cid and sec) else None


class RedditClient:
    def __init__(self, cache_dir: Path, timeframe: str = "year",
                 min_interval: float = 1.5, max_retries: int = 3):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeframe = timeframe
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_call = 0.0
        self._token: str | None = None
        self._token_exp = 0.0
        self._client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0)

    # -- auth ----------------------------------------------------------------

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_exp - 30:
            return self._token
        creds = load_credentials()
        if not creds:
            raise RedditUnavailable("no Reddit credentials (VBI_REDDIT_CLIENT_ID/SECRET or config/reddit.ini)")
        resp = self._client.post(TOKEN_URL, auth=creds, data={"grant_type": "client_credentials"})
        if resp.status_code != 200:
            raise RedditUnavailable(f"token request failed: HTTP {resp.status_code}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

    # -- fetch ---------------------------------------------------------------

    def fetch(self, brand: str, cache_only: bool = False) -> int | None:
        """Trailing-year fashion-subreddit comment volume for a brand.

        None = not fetched (cache miss under cache_only, or creds/API error) →
        ineligible. An integer (incl. 0) = fetched.
        """
        digest = hashlib.sha256(f"{brand}|{self.timeframe}".encode("utf-8")).hexdigest()[:16]
        slug = "".join(c for c in brand if c.isalnum())[:36]
        cache_file = self.cache_dir / f"{slug}_{self.timeframe}_{digest}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8")).get("comments")
        if cache_only:
            return None

        url = f"{OAUTH}/r/{FASHION_SUBS}/search"
        params = {"q": f'"{brand}"', "restrict_sr": "true", "limit": 100,
                  "sort": "comments", "t": self.timeframe, "type": "link", "raw_json": 1}
        for attempt in range(self._max_retries):
            try:
                self._throttle()
                token = self._ensure_token()
                resp = self._client.get(url, params=params,
                                        headers={"Authorization": f"Bearer {token}"})
                self._last_call = time.monotonic()
                if resp.status_code == 429 or resp.status_code >= 500:
                    time.sleep(5 * (attempt + 1)); continue
                if resp.status_code == 401:
                    self._token = None; continue        # token expired — refresh
                resp.raise_for_status()
                children = resp.json().get("data", {}).get("children", [])
                posts = len(children)
                comments = sum(c["data"].get("num_comments", 0) for c in children)
                cache_file.write_text(json.dumps({"posts": posts, "comments": comments}),
                                      encoding="utf-8")
                return comments
            except RedditUnavailable:
                return None
            except Exception:
                time.sleep(3 * (attempt + 1))
        return None

    def close(self) -> None:
        self._client.close()
