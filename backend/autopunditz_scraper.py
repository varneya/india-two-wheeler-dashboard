"""
AutoPunditz scraper.

AutoPunditz publishes monthly two-wheeler sales analysis posts on Wix at
https://www.autopunditz.com/post/<slug>. We consume two distinct post types:

  1. Per-brand monthly posts ("royal-enfield-sales-march-2026-analysis"):
     prose embeds per-model unit counts ("Classic 350 ... 37,144 units").
     Extracted into sales_data with source='autopunditz'.

  2. Monthly aggregate posts ("india-two-wheeler-sales-feb-2026-..."):
     prose embeds ~11 OEM brand totals. Extracted into wholesale_brand_sales
     with source='autopunditz'.

Discovery uses the Wix sitemap (sitemap.xml -> blog-posts-sitemap.xml) which
deterministically lists every published post URL.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

import bike_catalogue
from bike_registry import BRAND_DISPLAY, BRANDS, NON_MODELS

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SITEMAP_INDEX = "https://www.autopunditz.com/sitemap.xml"
POST_PREFIX = "https://www.autopunditz.com/post/"

# Map AutoPunditz's prose OEM names to our brand_id catalogue.
# Order matters — longer/more-specific phrases must come first so
# "honda motorcycle & scooter" wins over "honda motorcycle".
#
# Scoped to the seven major Indian two-wheeler OEMs that AutoPunditz
# consistently features as sentence subjects in monthly aggregate prose.
# Niche brands (Aprilia, Triumph, Kawasaki, BMW, Husqvarna, Harley-Davidson)
# tend to appear in subordinate clauses or context phrases — including them
# produces false positives like 'Piaggio Vehicles ... sells Vespa and Aprilia
# scooters, recorded 3,009 units' attributing 3,009 to Aprilia. Niche-brand
# wholesale numbers come from RushLane and FADA instead.
OEM_MAP: list[tuple[str, str]] = [
    ("hero motocorp",                  "hero"),
    ("honda motorcycle & scooter",     "honda"),
    ("honda motorcycle and scooter",   "honda"),
    ("honda motorcycle",               "honda"),
    ("tvs motor",                      "tvs"),
    ("bajaj auto",                     "bajaj"),
    ("suzuki motorcycle",              "suzuki"),
    ("royal enfield",                  "royal-enfield"),
    ("royal-enfield",                  "royal-enfield"),
    ("yamaha motor",                   "yamaha"),
    ("india yamaha",                   "yamaha"),
]

_MONTH_NAMES = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "sept": "09",
    "oct": "10", "nov": "11", "dec": "12",
}

# Regex to find a "<month> <year>" anywhere in a slug.
_MONTH_RE = re.compile(
    r"(?:^|-)(" + "|".join(_MONTH_NAMES.keys()) + r")-(\d{4})(?:-|$)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 20) -> requests.Response | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        print(f"[autopunditz] GET failed {url}: {e}")
        return None


def fetch_article_text(url: str) -> str | None:
    """Fetch a post and return its body text. Strips nav/footer/script
    so the prose extractor doesn't catch boilerplate numbers."""
    resp = _get(url)
    if not resp:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
        tag.decompose()
    # Wix wraps the post body in <div data-hook="post-description"> or similar,
    # but extracting the whole body text and relying on regex sentence-bounds
    # works fine for our use.
    text = soup.get_text(separator="\n")
    # Collapse runs of blank lines so the regex sentence-window is reliable
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text


# ---------------------------------------------------------------------------
# URL discovery via Wix sitemap
# ---------------------------------------------------------------------------

def _parse_sitemap_xml(xml_bytes: bytes) -> list[str]:
    """Return the list of <loc> URLs from a sitemap.xml or sitemap-index."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    # Strip namespace so we can match <loc> regardless of the xmlns.
    locs = []
    for elem in root.iter():
        tag = elem.tag.split("}", 1)[-1]
        if tag == "loc" and elem.text:
            locs.append(elem.text.strip())
    return locs


def _slug_from_url(url: str) -> str:
    """'https://www.autopunditz.com/post/yamaha-india-sales-march-2026-analysis'
    -> 'yamaha-india-sales-march-2026-analysis'."""
    return url.rstrip("/").rsplit("/", 1)[-1]


def _month_from_slug(slug: str) -> str | None:
    m = _MONTH_RE.search(slug.lower())
    if not m:
        return None
    mon, year = m.group(1).lower(), m.group(2)
    mm = _MONTH_NAMES.get(mon)
    if not mm:
        return None
    return f"{year}-{mm}"


def _brand_from_slug(slug: str) -> str | None:
    """Return the brand_id when the slug starts with a known brand prefix.
    Sorted by length desc so 'royal-enfield' matches before 'royal' and
    'harley-davidson' before 'harley'."""
    s = slug.lower()
    for brand_id in sorted(BRANDS, key=len, reverse=True):
        if s == brand_id or s.startswith(brand_id + "-"):
            return brand_id
    return None


def _classify_post(url: str) -> dict | None:
    """Classify an AutoPunditz post URL into 'brand' or 'aggregate' (or skip).
    Returns {url, kind, brand?, month} or None."""
    if not url.startswith(POST_PREFIX):
        return None
    slug = _slug_from_url(url).lower()
    if "sales" not in slug:
        return None
    month = _month_from_slug(slug)
    if not month:
        return None
    brand = _brand_from_slug(slug)
    if brand:
        return {"url": url, "kind": "brand", "brand": brand, "month": month}
    if ("two-wheeler-sales" in slug or "2-wheeler-sales" in slug
            or "2w-sales" in slug or "two-wheeler-industry" in slug):
        return {"url": url, "kind": "aggregate", "brand": None, "month": month}
    return None


def discover_post_urls(limit: int = 500) -> list[dict]:
    """Walk the Wix sitemap and return classified post entries.
    [{url, kind, brand?, month}], newest month first."""
    resp = _get(SITEMAP_INDEX)
    if not resp:
        return []
    sub_sitemaps = _parse_sitemap_xml(resp.content)
    # We only care about the blog-posts sitemap, but follow anything that
    # mentions "post" in its URL just in case Wix changes the naming.
    candidates = [s for s in sub_sitemaps if "post" in s.lower()]
    if not candidates:
        candidates = sub_sitemaps

    all_urls: set[str] = set()
    for sm in candidates:
        sub = _get(sm)
        if not sub:
            continue
        all_urls.update(_parse_sitemap_xml(sub.content))

    classified: list[dict] = []
    for url in all_urls:
        entry = _classify_post(url)
        if entry:
            classified.append(entry)
    classified.sort(key=lambda e: e["month"], reverse=True)
    print(f"[autopunditz] discovered {len(classified)} relevant posts "
          f"({sum(1 for e in classified if e['kind']=='brand')} brand, "
          f"{sum(1 for e in classified if e['kind']=='aggregate')} aggregate)")
    return classified[:limit]


# ---------------------------------------------------------------------------
# Per-brand prose -> per-bike units
# ---------------------------------------------------------------------------

def _make_units_pattern(keyword: str) -> re.Pattern:
    """Match '<keyword> ... NN,NNN units' within a tight window. AutoPunditz
    formats sales as bulleted lists, where most models have ONLY a YoY
    percentage with no absolute number. A loose window would let the regex
    drift into the NEXT bullet's number, producing false positives.

    The window of 60 chars handles all legitimate gaps we've seen:
      'Jupiter:\\n 1,24,771 units' (3 chars)
      'Vida EV posted 17,110 units' (8 chars)
      'Classic 350 \\n continued to lead sales with 37,144 units' (~32 chars)
    while rejecting the cross-bullet drift seen in Hero's prose where
    'Karizma' is 90+ chars from an unrelated 'HD X440 ... 2,202 units' bullet.
    Disallows period only (sentence boundary)."""
    kw = re.escape(keyword)
    return re.compile(
        rf"\b{kw}\b[^.]{{0,60}}?([\d]{{1,3}}(?:,\d{{2,3}})+|\d{{3,7}})\s*units?\b",
        re.IGNORECASE,
    )


def parse_bikes_from_prose(text: str, brand_id: str) -> list[dict]:
    """For an AutoPunditz per-brand post, walk every catalogue model in `brand_id`
    and try to find '<keyword> ... NN,NNN units' in the prose. Returns
    [{brand, model, canonical, bike_id, bikewale_slug, keywords, units}].

    Different from bike_registry.parse_bikes_from_article: that helper derives
    candidates from the URL slug (RushLane). AutoPunditz URLs only carry the
    brand, so we exhaustively check every model in the catalogue for the brand.
    The per-bike units floor + ceiling guard against prose false-positives
    (e.g. "Classic 350" near "350 cc" picking up "350" as units)."""
    if not text or brand_id not in bike_catalogue.CATALOGUE:
        return []

    models = bike_catalogue.get_brand_models(brand_id)
    out: dict[str, dict] = {}

    for entry in models:
        canonical = entry["canonical"]
        keywords = list(entry.get("keywords") or [canonical])
        # Also try the canonical (in case it differs from keywords)
        if canonical not in keywords:
            keywords.insert(0, canonical)

        floor = bike_catalogue.min_units_for(canonical)
        ceiling = 200_000

        units = None
        for kw in keywords:
            if not kw or kw.lower() in NON_MODELS:
                continue
            pat = _make_units_pattern(kw)
            m = pat.search(text)
            if not m:
                continue
            try:
                candidate_units = int(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if floor <= candidate_units <= ceiling:
                units = candidate_units
                break

        if units is None:
            continue

        bike_id = bike_catalogue.make_bike_id(brand_id, canonical)
        existing = out.get(bike_id)
        if existing and existing["units"] >= units:
            continue
        out[bike_id] = {
            "brand": brand_id,
            "model": canonical,
            "canonical": canonical,
            "bike_id": bike_id,
            "bikewale_slug": entry.get("bikewale"),
            "keywords": keywords,
            "units": units,
        }

    return list(out.values())


# ---------------------------------------------------------------------------
# Aggregate-post brand totals
# ---------------------------------------------------------------------------

def _make_brand_units_pattern(oem_phrase: str) -> re.Pattern:
    """'<OEM phrase> ... NN,NN,NNN units' in a sentence. Indian or Western
    number formats both accepted. We rely on OEM_MAP being scoped to the
    major Indian OEMs whose names appear unambiguously as sentence subjects
    in AutoPunditz prose; niche brands often appear in subordinate clauses
    (e.g. 'Piaggio Vehicles ... sells Vespa and Aprilia scooters, recorded
    3,009 units') and are excluded from OEM_MAP to avoid false positives."""
    phrase = re.escape(oem_phrase)
    return re.compile(
        rf"\b{phrase}\b[^.]{{0,250}}?([\d]{{1,3}}(?:,\d{{2,3}})+|\d{{4,8}})\s*units?\b",
        re.IGNORECASE,
    )


def _parse_aggregate_post(text: str, source_url: str, month: str) -> list[dict]:
    """Extract brand-level totals from a monthly aggregate post.
    Returns [{brand_id, month, units, source_url}]."""
    if not text:
        return []

    found: dict[str, dict] = {}
    text_lc = text.lower()

    for needle, brand_id in OEM_MAP:
        if not brand_id:
            continue
        if needle not in text_lc:
            continue
        # Prefer a variant of the prose phrase that matches case-insensitively
        pat = _make_brand_units_pattern(needle)
        m = pat.search(text)
        if not m:
            continue
        try:
            units = int(m.group(1).replace(",", ""))
        except ValueError:
            continue
        # Brand-monthly floor: anything below 100 is almost certainly a misparse.
        # Ceiling: 1.5M units would be the whole industry — sanity guard.
        if not (100 <= units <= 1_500_000):
            continue
        existing = found.get(brand_id)
        if existing and existing["units"] >= units:
            continue
        found[brand_id] = {
            "brand_id": brand_id,
            "month": month,
            "units": units,
            "source_url": source_url,
        }
    return list(found.values())


# ---------------------------------------------------------------------------
# Top-level scrape entrypoints
# ---------------------------------------------------------------------------

def scrape_brand_posts(limit: int = 200) -> list[dict]:
    """Discover brand posts and fetch each one's text.
    Returns [{url, text, brand, month}] (text=None on fetch failure -> caller skips)."""
    posts = [p for p in discover_post_urls(limit=limit) if p["kind"] == "brand"]
    out: list[dict] = []
    for p in posts:
        text = fetch_article_text(p["url"])
        if not text:
            continue
        out.append({
            "url": p["url"],
            "text": text,
            "brand": p["brand"],
            "month": p["month"],
        })
    print(f"[autopunditz] fetched {len(out)} brand posts")
    return out


def scrape_aggregate_posts(limit: int = 100) -> list[dict]:
    """Discover aggregate posts, fetch + parse each, dedup by (brand_id, month).
    Returns [{brand_id, month, units, source_url}]."""
    posts = [p for p in discover_post_urls(limit=limit) if p["kind"] == "aggregate"]
    rows: dict[tuple[str, str], dict] = {}
    for p in posts:
        text = fetch_article_text(p["url"])
        if not text:
            continue
        for entry in _parse_aggregate_post(text, p["url"], p["month"]):
            key = (entry["brand_id"], entry["month"])
            existing = rows.get(key)
            if existing and existing["units"] >= entry["units"]:
                continue
            rows[key] = entry
    print(f"[autopunditz] parsed {len(rows)} brand-month rows from {len(posts)} aggregate posts")
    return list(rows.values())
