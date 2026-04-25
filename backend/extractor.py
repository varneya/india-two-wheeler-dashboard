"""
Per-bike sales extractor (regex/rule-based, no API key).

Strategy:
  1. Parse the month from the article URL.
  2. For each keyword associated with a bike, search the article text
     using a few patterns ordered most-specific to least-specific.
"""

import re

import bike_catalogue

# --- Month parsing from URL ---

MONTH_NAMES = {
    "jan": "01", "january": "01",
    "feb": "02", "february": "02",
    "mar": "03", "march": "03",
    "apr": "04", "april": "04",
    "may": "05",
    "jun": "06", "june": "06",
    "jul": "07", "july": "07",
    "aug": "08", "august": "08",
    "sep": "09", "sept": "09", "september": "09",
    "oct": "10", "october": "10",
    "nov": "11", "november": "11",
    "dec": "12", "december": "12",
}

_URL_MONTH_RE = re.compile(
    r"(?:^|[-/])(" + "|".join(MONTH_NAMES.keys()) + r")-(\d{4})(?:[-/]|$)",
    re.IGNORECASE,
)


def month_from_url(url: str) -> str | None:
    m = _URL_MONTH_RE.search(url)
    if not m:
        return None
    mon_str, year = m.group(1).lower(), m.group(2)
    mon_num = MONTH_NAMES.get(mon_str)
    if not mon_num:
        return None
    return f"{year}-{mon_num}"


# Backwards-compat alias
_month_from_url = month_from_url


# --- Unit extraction ---

def _build_patterns(keyword: str) -> list[re.Pattern]:
    kw = re.escape(keyword)
    return [
        # "<KW> ... 14,951 units" — keyword somewhere before a number+units phrase,
        # within ~120 chars and same sentence
        re.compile(rf"{kw}(?:[\s\-]*\d+)?[^.\n]{{0,120}}?([\d,]+)\s*units", re.IGNORECASE),
        # "14,951 units ... <KW>" — number first, keyword within ~80 chars after
        re.compile(rf"([\d,]+)\s*units[^.\n]{{0,80}}{kw}", re.IGNORECASE),
        # "<KW> ... 6,948" — no "units" word, but tighter window
        re.compile(rf"{kw}(?:[\s\-]*\d+)?[^.\n]{{0,40}}?([\d,]+)\b", re.IGNORECASE),
    ]


def _parse_units(raw: str) -> int | None:
    """Parse a unit count. Returns None for negative or impossibly-large values.
    The per-bike sanity floor is applied by the caller."""
    cleaned = raw.replace(",", "").strip()
    try:
        val = int(cleaned)
        return val if 0 < val <= 1_000_000 else None
    except ValueError:
        return None


def extract_sales_for_bike(article_text: str, article_url: str,
                           bike: dict) -> dict | None:
    """
    bike: dict with at least 'id', 'keywords' (list[str]), 'launch_month' (str | None),
          'model' (canonical name, used for the per-bike unit floor).
    Returns {bike_id, month, units_sold, source_url, confidence} or None.
    """
    if not article_text:
        return None

    month = month_from_url(article_url)
    if not month:
        return None

    launch = bike.get("launch_month")
    if launch and month < launch:
        return None

    # Per-bike sanity floor (e.g. Activa = 50,000) so a stray "125cc" near the
    # bike's name doesn't slip through.
    canonical = bike.get("model") or bike.get("canonical") or ""
    floor = bike_catalogue.min_units_for(canonical) if canonical else 100

    for kw in bike.get("keywords", []) or []:
        for pat in _build_patterns(kw):
            m = pat.search(article_text)
            if m:
                units = _parse_units(m.group(1))
                if units is None or units < floor:
                    continue
                return {
                    "bike_id": bike["id"],
                    "month": month,
                    "units_sold": units,
                    "source_url": article_url,
                    "confidence": "high" if " units" in m.group(0).lower() else "medium",
                }

    return None


# Legacy single-bike entry point — kept only so older callers don't break.
def extract_xsr_sales(article_text: str, article_url: str) -> dict | None:
    bike = {
        "id": "yamaha-xsr-155",
        "keywords": ["XSR 155", "XSR"],
        "launch_month": "2025-11",
    }
    res = extract_sales_for_bike(article_text, article_url, bike)
    if res is None:
        return None
    # Old callers expect 'month'/'units_sold'/'source_url'/'confidence' without bike_id
    out = {k: v for k, v in res.items() if k != "bike_id"}
    return out
