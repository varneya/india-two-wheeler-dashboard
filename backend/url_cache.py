"""
HTTP conditional-GET layer.

Every refresh used to re-fetch every URL. Most of those URLs are immutable
once published (FADA monthly PDFs, AutoPunditz monthly posts, RushLane
sales-breakup articles), so the network + parse cost was wasted.

This module wraps requests.get with an If-Modified-Since / If-None-Match
shortcut driven by the `url_cache` table:

  - First fetch: GET, store ETag/Last-Modified/SHA256(body), return body.
  - Subsequent fetch: send If-None-Match + If-Modified-Since.
      * 304 Not Modified  -> short-circuit; caller skips parsing.
      * 200 + body hash unchanged -> short-circuit; same outcome.
      * 200 + new hash    -> return body, update cache, caller parses.

Hosts that ignore validators (some Wix sites, Reddit-style endpoints) still
benefit from the content-hash compare path. The fallback is a single round
trip rather than full parse work.

Usage from scrapers:

    from url_cache import conditional_get

    resp, was_cached = conditional_get(url, headers=HEADERS)
    if was_cached:
        return None  # caller skips work — data already in DB from last run
    if not resp:
        return None  # network failure
    # ... parse resp.text / resp.content as before ...
"""

from __future__ import annotations

import hashlib
import threading

import requests

import database


# Thread-local counters so the refresh pipeline can report
# "X cached / Y fetched" per stage without threading state through every
# scraper's call signature. Reset between stages with reset_stats().
_stats_lock = threading.Lock()
_stats = {"cached": 0, "fetched": 0, "failed": 0}


def reset_stats() -> dict:
    """Snapshot + zero the counters. Call this between refresh-all stages."""
    with _stats_lock:
        snap = dict(_stats)
        for k in _stats:
            _stats[k] = 0
    return snap


def get_stats() -> dict:
    with _stats_lock:
        return dict(_stats)


def _bump(key: str):
    with _stats_lock:
        _stats[key] = _stats.get(key, 0) + 1


def _hash_body(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def conditional_get(
    url: str,
    headers: dict | None = None,
    timeout: int = 20,
) -> tuple[requests.Response | None, bool]:
    """GET `url` with conditional headers from cache, return (response, was_cached).

    was_cached=True means the caller can skip parsing entirely — the body has
    not changed since our last successful fetch. Either:
      - The server returned 304 Not Modified, or
      - The server returned 200 but the body's SHA256 matches the cached hash
        (this catches hosts that ignore If-None-Match / If-Modified-Since).

    On 304 the returned response is the 304 itself (no body); on 200 it's the
    new response. On network failure both elements are None / False so the
    caller falls through to its existing error-handling path.
    """
    cache = database.get_url_cache_entry(url)
    req_headers = dict(headers or {})
    if cache:
        if cache.get("etag"):
            req_headers["If-None-Match"] = cache["etag"]
        if cache.get("last_modified"):
            req_headers["If-Modified-Since"] = cache["last_modified"]

    try:
        resp = requests.get(url, headers=req_headers, timeout=timeout)
    except requests.RequestException as e:
        print(f"[url_cache] GET failed {url}: {e}")
        _bump("failed")
        return None, False

    if resp.status_code == 304:
        # Server confirmed unchanged. Refresh last_fetched_at so the row
        # ages predictably.
        database.upsert_url_cache(
            url=url,
            etag=cache.get("etag") if cache else None,
            last_modified=cache.get("last_modified") if cache else None,
            content_hash=cache.get("content_hash") if cache else None,
            last_status=304,
        )
        _bump("cached")
        return resp, True

    if resp.status_code != 200:
        # Don't overwrite a known-good cache with a transient failure.
        _bump("failed")
        return resp, False

    # 200 OK — compare body hash against cache to catch hosts that ignore
    # validators. If unchanged, short-circuit but still refresh the
    # last_fetched_at + validators (the server may have rotated ETag).
    new_hash = _hash_body(resp.content)
    new_etag = resp.headers.get("ETag")
    new_last_mod = resp.headers.get("Last-Modified")
    same = bool(cache and cache.get("content_hash") == new_hash)
    database.upsert_url_cache(
        url=url,
        etag=new_etag,
        last_modified=new_last_mod,
        content_hash=new_hash,
        last_status=200,
    )
    _bump("cached" if same else "fetched")
    return resp, same
