"""
RushLane discovery + article fetching — multi-brand version.

For each brand we know about, we hit RushLane's search page and collect
URLs that match the sales-breakup / india-sales article pattern.
"""

import random
import re
import time

import requests
from bs4 import BeautifulSoup

import url_cache
from bike_registry import BRANDS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}

# RushLane search endpoints — one per brand, plus generic queries
RUSHLANE_SEARCHES = (
    [f"https://www.rushlane.com/?s={brand}+sales+breakup" for brand in BRANDS]
    + [f"https://www.rushlane.com/?s={brand}+india+sales" for brand in BRANDS]
)

# Match article URLs for any of our known brands.
URL_PATTERN = re.compile(
    r"rushlane\.com/(?:" + "|".join(re.escape(b) for b in BRANDS) + r")"
    r"-(?:sales-breakup|india-sales)-[a-z0-9\-]+-\d+\.html",
    re.IGNORECASE,
)

# Verified seed URLs we know are good (saves an extra search round-trip
# the first time the DB is empty).
KNOWN_URLS = [
    # Yamaha (kept from previous deployment)
    "https://www.rushlane.com/yamaha-sales-breakup-nov-2025-fz-r15-mt-15-rayzr-fascino-aerox-12536880.html",
    "https://www.rushlane.com/yamaha-sales-breakup-dec-2025-xsr155-becomes-top-seller-12538808.html",
    "https://www.rushlane.com/yamaha-sales-breakup-feb-2026-rayzr-fz-mt15-12542486.html",
    "https://www.rushlane.com/yamaha-sales-breakup-march-2026-rayzr-fz-mt15-r15-12544753.html",
    "https://www.rushlane.com/yamaha-india-sales-jan-2026-155cc-now-accounts-for-41-of-total-sales-12540726.html",
]


def _get(url: str, timeout: int = 15) -> requests.Response | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        print(f"[scraper] GET failed for {url}: {e}")
        return None


def discover_article_urls() -> list[str]:
    urls: set[str] = set(KNOWN_URLS)

    for search_url in RUSHLANE_SEARCHES:
        resp = _get(search_url)
        if resp:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                if URL_PATTERN.search(href):
                    urls.add(href.split("?")[0])
        time.sleep(random.uniform(1, 2))

    print(f"[scraper] Discovered {len(urls)} article URLs across {len(BRANDS)} brands")
    return sorted(urls)


def fetch_article_text(url: str) -> str | None:
    """Fetch and parse a RushLane article. Uses HTTP conditional-GET; returns
    None when the article hasn't changed since the last successful fetch
    (caller should treat that the same as 'no new data to insert')."""
    resp, was_cached = url_cache.conditional_get(url, headers=HEADERS, timeout=15)
    if was_cached:
        return None
    if not resp or resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    body = soup.find("div", class_="entry-content") or soup.find("article") or soup.find("main")
    if not body:
        body = soup

    tags = body.find_all(["p", "li", "td", "th", "h2", "h3"])
    text = "\n".join(t.get_text(" ", strip=True) for t in tags if t.get_text(strip=True))
    return text or None


def scrape_all() -> list[dict]:
    """Return list of {url, text} dicts for all discoverable articles whose
    body changed since the last refresh. URLs whose content is unchanged are
    skipped (their data is already in sales_data from the prior run)."""
    urls = discover_article_urls()
    results = []
    for url in urls:
        text = fetch_article_text(url)
        if text:
            results.append({"url": url, "text": text})
            time.sleep(random.uniform(2, 4))
    return results
