"""Cached, rate-limited fetching.

Every page is written to disk before parsing. Two reasons:
  1. Re-runs and parser fixes never re-hit the source.
  2. When a parse fails you have the exact HTML that broke it.
"""

import hashlib
import time
from pathlib import Path

import requests

CACHE = Path("cache")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

_last_hit = {}
MIN_GAP = 1.5  # seconds between requests to the same host


def _host(url):
    return url.split("/")[2]


def get(url, force=False, timeout=30):
    CACHE.mkdir(exist_ok=True)
    key = hashlib.sha256(url.encode()).hexdigest()[:20]
    path = CACHE / f"{key}.html"
    if path.exists() and not force:
        return path.read_text(encoding="utf-8", errors="replace")

    h = _host(url)
    gap = time.time() - _last_hit.get(h, 0)
    if gap < MIN_GAP:
        time.sleep(MIN_GAP - gap)
    _last_hit[h] = time.time()

    r = requests.get(url, headers={"User-Agent": UA,
                                   "Accept-Language": "en-US,en;q=0.9"},
                     timeout=timeout)
    r.raise_for_status()
    path.write_text(r.text, encoding="utf-8")
    return r.text


def cached_path(url):
    key = hashlib.sha256(url.encode()).hexdigest()[:20]
    return CACHE / f"{key}.html"
