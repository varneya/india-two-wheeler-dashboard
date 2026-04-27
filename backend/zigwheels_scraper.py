"""
ZigWheels user-review scraper.

URL pattern: https://www.zigwheels.com/newbikes/{brand}/{model-slug}/user-reviews

We derive the URL from the bike's `bikewale_slug` (which is in the form
"{brand}-bikes/{model-slug}") by splitting on the dash and prefix-renaming.
This works for the catalogue we have today; future entries that diverge can
get an explicit override field.

ZigWheels exposes a stable numeric review id in markup (`id="review_538049"`),
which we use as the post_id seed so dedupe via `upsert_review` is robust.
The page typically shows ~4–10 top-level reviews on the default load.
"""

from __future__ import annotations

import random
import re
import time

import requests
from bs4 import BeautifulSoup

import database
import url_cache

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-IN,en;q=0.9",
}

BASE_URL = "https://www.zigwheels.com"
REVIEW_ID_RE = re.compile(r"review_(\d+)")


def _slug_to_zw_path(bikewale_slug: str) -> str | None:
    # bikewale_slug example: "yamaha-bikes/r15-v4"  ->  "newbikes/yamaha/r15-v4"
    if "-bikes/" not in bikewale_slug:
        return None
    brand_part, model = bikewale_slug.split("-bikes/", 1)
    return f"newbikes/{brand_part}/{model}"


def _extract_review_id(card) -> str | None:
    # The numeric id appears on a few descendant elements: reviewspan_like_X,
    # reviewanchor_X, review_X, ar-text-X. Pick the first match.
    for el in card.find_all(True):
        for attr in ("id", "class"):
            v = el.get(attr)
            if not v:
                continue
            blob = " ".join(v) if isinstance(v, list) else str(v)
            m = REVIEW_ID_RE.search(blob)
            if m:
                return m.group(1)
    return None


def _parse_card(card, bike_id: str, page_url: str) -> dict | None:
    rid = _extract_review_id(card)
    if not rid:
        return None

    author_el = card.select_one(".nw-profileName")
    title_el = card.select_one(".f-rv-h")
    body_el = card.select_one(".read-more p")

    author = author_el.get_text(strip=True) if author_el else "Anonymous"
    title = title_el.get_text(" ", strip=True) if title_el else ""
    body = body_el.get_text(" ", strip=True) if body_el else ""

    full = (title + ". " + body).strip(". ").strip() if title else body
    full = re.sub(r"\s+", " ", full)[:2000]
    if len(full) < 30:
        return None

    return {
        "bike_id": bike_id,
        "source": "zigwheels",
        "post_id": f"zigwheels:{rid}",
        "username": author or "Anonymous",
        "review_text": full,
        # Most ZigWheels reviews don't expose a numeric rating in the listing
        # markup; leave null and let PR 5's rating-signal logic handle absence.
        "overall_rating": None,
        "thread_url": page_url,
    }


def scrape_zigwheels_for_bike(bike: dict) -> list[dict]:
    slug = bike.get("bikewale_slug")
    bike_id = bike["id"]
    if not slug:
        print(f"[zigwheels] {bike_id}: no slug, skipping")
        return []
    zw_path = _slug_to_zw_path(slug)
    if not zw_path:
        print(f"[zigwheels] {bike_id}: cannot derive ZigWheels path from slug={slug!r}")
        return []

    time.sleep(random.uniform(1.0, 2.0))

    url = f"{BASE_URL}/{zw_path}/user-reviews"
    resp, was_cached = url_cache.conditional_get(url, headers=HEADERS, timeout=15)
    if was_cached:
        return []
    if not resp or resp.status_code != 200:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    container = soup.find(id="userReviews")
    if not container:
        print(f"[zigwheels] {bike_id}: no #userReviews container")
        return []

    out: dict[str, dict] = {}
    for card in container.select(".ncmt-c"):
        parsed = _parse_card(card, bike_id, url)
        if parsed and parsed["post_id"] not in out:
            out[parsed["post_id"]] = parsed

    items = list(out.values())
    if items:
        newest_id = items[0]["post_id"]
        cursor = database.get_review_cursor(bike_id, "zigwheels")
        if cursor == newest_id:
            return []
        database.upsert_review_cursor(bike_id, "zigwheels", newest_id)
    print(f"[zigwheels] {bike_id}: {len(items)} reviews")
    return items
