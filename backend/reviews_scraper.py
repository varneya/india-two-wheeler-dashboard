"""
Per-bike BikeWale reviews scraper.

Each bike has a `bikewale_slug` (e.g. "yamaha-bikes/xsr-155") that maps to
a URL of the form  https://www.bikewale.com/<slug>/reviews/.

BikeWale renders all reviews on the first page; the `?page=N` query param is
silently ignored (we verified page 1, 2, 3, 7, 10, 20 all return the same set).
We deduplicate by the BikeWale review ID embedded in each card's title link
(/reviews/<id>/), so the same review never gets stored twice.

Each card has:
  - `<a href="/.../reviews/<id>/">` for stable post_id
  - First `<p class="o-j4">` (or first non-empty paragraph): review title
  - Two paragraph siblings without a class: time-ago line, then username
  - First `<p class="o-j1">`: review body
  - Five `<svg aria-label="rating icon">` elements; filled stars carry class
    `o-k3`, empty stars `o-jN`. Count `o-k3` for the overall rating.
"""

import random
import re
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CARD_TESTID_RE = re.compile(r"^user-reviews-card-\d+$")
TIME_AGO_RE = re.compile(r"\d+\s*(?:days?|weeks?|months?|years?)\s*ago", re.I)
REVIEW_ID_RE = re.compile(r"/reviews/(\d+)")


def _bikewale_base(slug: str) -> str:
    slug = slug.strip("/")
    return f"https://www.bikewale.com/{slug}/reviews/"


def _parse_card(card, bike_id: str, fallback_idx: int, page_url: str) -> dict | None:
    """Parse a single review card. Returns None if the card doesn't look like
    a real review (no time-ago phrase or no body text)."""
    text = card.get_text(" ", strip=True)
    if not TIME_AGO_RE.search(text):
        return None

    # Stable review ID from the title link
    review_id = None
    link = card.find("a", href=REVIEW_ID_RE)
    if link:
        m = REVIEW_ID_RE.search(link.get("href", ""))
        if m:
            review_id = m.group(1)
    post_id = f"bikewale-{bike_id}-{review_id}" if review_id else f"bikewale-{bike_id}-fallback-{fallback_idx}"

    # Title — first paragraph with a class (BikeWale styles it as o-j4)
    title_p = next((p for p in card.find_all("p") if p.get("class")), None)
    title = title_p.get_text(strip=True) if title_p else None

    # Time-ago + username — paragraphs WITHOUT a class, in order
    no_class_ps = [p for p in card.find_all("p") if not p.get("class")]
    timeago = no_class_ps[0].get_text(strip=True) if len(no_class_ps) >= 1 else None
    username = (
        no_class_ps[1].get_text(strip=True) if len(no_class_ps) >= 2 else None
    )

    # Body text — first <p class="o-j1"> with substantive content
    body = ""
    for p in card.find_all("p", class_="o-j1"):
        candidate = p.get_text(" ", strip=True)
        if len(candidate) > 30:
            body = candidate
            break
    if not body:
        # fallback: longest paragraph
        all_ps = sorted(
            (p.get_text(" ", strip=True) for p in card.find_all("p")),
            key=len, reverse=True,
        )
        body = all_ps[0] if all_ps else ""

    # Rating — count filled stars (class "o-k3") among the first 5 rating icons
    rating = None
    icons = card.find_all("svg", attrs={"aria-label": "rating icon"})[:5]
    if icons:
        filled = sum(1 for ic in icons if "o-k3" in (ic.get("class") or []))
        if filled > 0:
            rating = float(filled)

    review_url = f"https://www.bikewale.com{link.get('href')}" if link else page_url

    # Compose a sensible review_text — title + body, capped
    full = (title + " " + body).strip() if title else body
    full = re.sub(r"\s+", " ", full)[:2000]

    return {
        "bike_id": bike_id,
        "source": "bikewale",
        "post_id": post_id,
        "username": username or f"BikeWale user {fallback_idx}",
        "review_text": full,
        "overall_rating": rating,
        "thread_url": review_url,
    }


def scrape_bikewale_for_bike(bike_id: str, slug: str) -> list[dict]:
    """Fetch the BikeWale reviews page once, parse every review card, dedupe
    by review ID. BikeWale's `?page=N` is fake — page 1 holds everything they
    expose statically."""
    base = _bikewale_base(slug)
    try:
        resp = requests.get(base, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[reviews_scraper] {bike_id}: GET failed: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.find_all(attrs={"data-testid": CARD_TESTID_RE})

    reviews: dict[str, dict] = {}
    for i, card in enumerate(cards):
        parsed = _parse_card(card, bike_id, i, base)
        if not parsed:
            continue
        # Dedupe by post_id (which encodes the review ID when available)
        if parsed["post_id"] not in reviews:
            reviews[parsed["post_id"]] = parsed

    out = list(reviews.values())
    rated = sum(1 for r in out if r["overall_rating"] is not None)
    print(f"[reviews_scraper] {bike_id}: {len(out)} reviews ({rated} with ratings)")
    return out


def scrape_reviews_for_bike(bike: dict) -> list[dict]:
    """bike: row from the bikes table (dict). Returns list of review dicts."""
    slug = bike.get("bikewale_slug")
    if not slug:
        print(f"[reviews_scraper] {bike['id']}: no bikewale_slug, skipping")
        return []
    # Polite delay so successive bikes don't hammer BikeWale
    time.sleep(random.uniform(0.5, 1.2))
    return scrape_bikewale_for_bike(bike["id"], slug)


# Legacy entry-point retained for any old callers.
def scrape_all_reviews() -> list[dict]:
    return scrape_bikewale_for_bike("yamaha-xsr-155", "yamaha-bikes/xsr-155")
