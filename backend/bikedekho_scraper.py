"""
BikeDekho user-review scraper.

URL pattern: https://www.bikedekho.com/{brand}-bikes/{model-slug}/reviews
Conveniently, the {brand}-bikes/{model-slug} portion is identical to the
bikewale_slug we already store per bike, so no per-bike override is needed —
the scraper just maps `bikewale_slug` straight into BikeDekho's URL.

BikeDekho's first reviews page typically holds 20–30 reviews — substantially
more than BikeWale's ~10. Each review carries an explicit numeric rating,
which we capture so the rating signal added in PR 5 has more data to lean on.

Reviews don't have a stable site-issued ID in the markup, so we fabricate a
deterministic post_id by hashing (author, date, title) — re-runs against the
same content yield the same id, so `upsert_review` deduplicates cleanly.
"""

from __future__ import annotations

import hashlib
import random
import re
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
}

BASE_URL = "https://www.bikedekho.com"


def _stable_post_id(bike_id: str, author: str, date: str, title: str) -> str:
    seed = f"{bike_id}|{author}|{date}|{title}".encode("utf-8")
    return f"bikedekho:{bike_id}:{hashlib.md5(seed).hexdigest()[:12]}"


def _parse_card(li, bike_id: str, page_url: str) -> dict | None:
    name_el = li.select_one(".authorSummary .name")
    rating_el = li.select_one(".ratingStarNew")
    title_el = li.select_one(".contentspace .title")
    body_el = li.select_one(".contentheight")

    if not (name_el and (title_el or body_el)):
        return None

    # name_el text looks like "saiful on Mar 27, 2026" — split on " on "
    name_text = re.sub(r"\s+", " ", name_el.get_text(" ", strip=True))
    parts = name_text.rsplit(" on ", 1)
    author = parts[0].strip() if parts else name_text
    date = parts[1].strip() if len(parts) == 2 else ""

    title = title_el.get_text(" ", strip=True) if title_el else ""
    body = body_el.get_text(" ", strip=True) if body_el else ""
    body = re.sub(r"\s*Read More\s*$", "", body).strip()

    full = (title + ". " + body).strip(". ").strip() if title else body
    full = re.sub(r"\s+", " ", full)[:2000]
    if len(full) < 30:
        return None

    rating: float | None = None
    if rating_el:
        try:
            rating = float(rating_el.get_text(strip=True))
        except (TypeError, ValueError):
            rating = None

    post_id = _stable_post_id(bike_id, author, date, title)
    return {
        "bike_id": bike_id,
        "source": "bikedekho",
        "post_id": post_id,
        "username": author or "BikeDekho user",
        "review_text": full,
        "overall_rating": rating,
        "thread_url": page_url,
    }


def scrape_bikedekho_for_bike(bike: dict) -> list[dict]:
    """bike: row from the bikes table (dict). Returns a list of review dicts.
    Returns [] if the bike has no bikewale_slug (we reuse it as the BikeDekho
    slug) or if the page 404s / has no parseable cards."""
    slug = bike.get("bikewale_slug")
    bike_id = bike["id"]
    if not slug:
        print(f"[bikedekho] {bike_id}: no slug, skipping")
        return []

    # Polite delay between bikes; cumulative load on the site
    time.sleep(random.uniform(1.0, 2.0))

    url = f"{BASE_URL}/{slug}/reviews"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
    except requests.RequestException as e:
        print(f"[bikedekho] {bike_id}: GET failed: {e}")
        return []
    if resp.status_code != 200:
        print(f"[bikedekho] {bike_id}: HTTP {resp.status_code}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    ul = soup.select_one("ul.reviewList")
    if not ul:
        print(f"[bikedekho] {bike_id}: no reviewList container")
        return []

    out: dict[str, dict] = {}
    for li in ul.find_all("li", recursive=False):
        parsed = _parse_card(li, bike_id, url)
        if parsed and parsed["post_id"] not in out:
            out[parsed["post_id"]] = parsed

    rated = sum(1 for r in out.values() if r["overall_rating"] is not None)
    print(f"[bikedekho] {bike_id}: {len(out)} reviews ({rated} with ratings)")
    return list(out.values())
