"""
FADA monthly retail data scraper.

FADA (Federation of Automobile Dealers Associations) publishes monthly
"Vehicle Retail Data" PDFs on their homepage. Each PDF contains a
"Two-Wheeler OEM" table with brand-level retail (registration) units.

We:
  1. Discover PDF URLs from fada.in homepage + press-release-list page.
  2. For each monthly PDF, extract the 2W OEM table via pdfplumber.
  3. Map FADA's verbose company names to our brand_ids.

Returns rows of {brand_id, month, units, source_url}.
"""

from __future__ import annotations

import io
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
}

FADA_HOME = "https://fada.in/"
FADA_PRESS = "https://fada.in/press-release-list.php"

# Map FADA's verbose OEM names to our brand_id catalogue.
# Match by lowercased substring — covers "BAJAJ AUTO LTD" / "BAJAJ AUTO GROUP".
OEM_MAP: list[tuple[str, str]] = [
    ("hero motocorp",      "hero"),
    ("honda motorcycle",   "honda"),
    ("tvs motor",          "tvs"),
    ("bajaj auto",         "bajaj"),
    ("suzuki motorcycle",  "suzuki"),
    ("royal-enfield",      "royal-enfield"),
    ("royal enfield",      "royal-enfield"),
    ("india yamaha",       "yamaha"),
    ("yamaha motor",       "yamaha"),
    ("ktm",                "ktm"),
    ("kawasaki",           "kawasaki"),
    ("aprilia",            "aprilia"),
    ("triumph",            "triumph"),
    ("ducati",             "ducati"),
    ("bmw motorrad",       "bmw"),
    ("harley",             "harley-davidson"),
    ("husqvarna",          "husqvarna"),
]

# "FADA releases February 2026 Vehicle Retail Data.pdf"
# "FADA releases FY 2026 and March 2026 Vehicle Retail Data.pdf"
_MONTH_NAMES = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "sept": "09",
    "oct": "10", "nov": "11", "dec": "12",
}


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _filename_to_month(name: str) -> str | None:
    """Parse 'FADA releases February 2026 Vehicle Retail Data.pdf' -> '2026-02'.
    Falls back to last-mentioned month if multiple are present."""
    name = name.lower()
    matches = re.findall(
        r"(january|february|march|april|may|june|july|august|"
        r"september|october|november|december|jan|feb|mar|apr|"
        r"jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{4})",
        name,
    )
    if not matches:
        return None
    # Take the last match (e.g. "FY 2026 and March 2026" -> March 2026)
    mon_word, year = matches[-1]
    mm = _MONTH_NAMES.get(mon_word)
    if not mm:
        return None
    return f"{year}-{mm}"


def discover_monthly_pdfs(limit: int = 24) -> list[dict]:
    """Return [{url, month, filename}] for monthly retail PDFs."""
    seen: dict[str, dict] = {}
    for page_url in (FADA_HOME, FADA_PRESS):
        try:
            r = requests.get(page_url, headers=HEADERS, timeout=15)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"[fada] {page_url} failed: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.lower().endswith(".pdf"):
                continue
            full = urljoin(page_url, href)
            # Only "Vehicle Retail Data" PDFs (skip Vyapar conferences etc.)
            fname = href.rsplit("/", 1)[-1].lower()
            if "vehicle retail" not in fname.replace("%20", " "):
                continue
            month = _filename_to_month(fname.replace("%20", " "))
            if not month:
                continue
            seen[full] = {"url": full, "month": month, "filename": fname}
    out = sorted(seen.values(), key=lambda x: x["month"], reverse=True)
    print(f"[fada] discovered {len(out)} monthly retail PDFs")
    return out[:limit]


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def _normalise_units(raw: str) -> int | None:
    if raw is None:
        return None
    cleaned = re.sub(r"[^\d]", "", str(raw))
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _oem_to_brand_id(oem_name: str) -> str | None:
    if not oem_name:
        return None
    lo = oem_name.lower()
    for needle, brand_id in OEM_MAP:
        if needle in lo:
            return brand_id
    return None


# Month abbreviation lookup for matching FADA's "Mar'26" / "Feb'26" headers.
_MM_TO_ABBR = {
    "01": "jan", "02": "feb", "03": "mar", "04": "apr",
    "05": "may", "06": "jun", "07": "jul", "08": "aug",
    "09": "sep", "10": "oct", "11": "nov", "12": "dec",
}


def _is_2w_oem_header(row: list) -> bool:
    """Recognise the 'Two-Wheeler OEM | <month>'YY | Market Share | ...' header row."""
    if not row:
        return False
    first = (row[0] or "").lower()
    return "two-wheeler" in first and "oem" in first


def _find_target_column(header: list, target_month: str) -> int | None:
    """Given a header row and a target month YYYY-MM, return the column index
    whose label matches that month (e.g. "Mar'26" or "March 2026").
    Returns None if no column matches — caller can skip that table."""
    year, mm = target_month.split("-")
    yy = year[2:]
    abbr = _MM_TO_ABBR.get(mm, "")
    full_name_re = re.compile(rf"\b({abbr}\w*)\s*[\'’]?{yy}\b", re.IGNORECASE)
    for idx, cell in enumerate(header):
        if not cell:
            continue
        text = str(cell).lower().replace("\n", " ")
        if "market share" in text:
            continue   # skip percentage columns
        if full_name_re.search(text):
            return idx
    return None


def parse_pdf_2w_oems(pdf_bytes: bytes, target_month: str) -> list[dict]:
    """Extract [{oem, units}] for the 2W OEM table whose header has a column
    matching `target_month` (e.g. '2026-03'). FADA PDFs sometimes contain
    multiple OEM tables (FY totals vs single-month) — we pick the right one."""
    if not PDFPLUMBER_AVAILABLE:
        raise RuntimeError("pdfplumber not installed. Run: pip install pdfplumber")

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for tbl in page.extract_tables() or []:
                if not tbl or not _is_2w_oem_header(tbl[0]):
                    continue
                col = _find_target_column(tbl[0], target_month)
                if col is None:
                    # This table doesn't have the target month — skip
                    continue
                out: list[dict] = []
                for row in tbl[1:]:
                    if not row or len(row) <= col:
                        continue
                    oem = (row[0] or "").strip()
                    units = _normalise_units(row[col])
                    if not oem or units is None or units < 100:
                        continue
                    out.append({"oem": oem, "units": units})
                if out:
                    return out
    return []


def fetch_and_parse_pdf(url: str, target_month: str) -> list[dict]:
    """Download a FADA PDF and return [{oem, units}] for the given month."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[fada] download failed {url}: {e}")
        return []
    try:
        return parse_pdf_2w_oems(r.content, target_month)
    except Exception as e:
        print(f"[fada] parse failed {url}: {e}")
        return []


# ---------------------------------------------------------------------------
# Top-level: returns brand-level rows ready for the DB
# ---------------------------------------------------------------------------

def scrape_all_retail(limit_pdfs: int = 24) -> list[dict]:
    """
    Returns [{brand_id, month, units, source_url}] across all available
    monthly PDFs, deduped by (brand_id, month) — latest scrape wins.
    """
    pdfs = discover_monthly_pdfs(limit=limit_pdfs)
    rows: dict[tuple[str, str], dict] = {}
    for pdf in pdfs:
        oems = fetch_and_parse_pdf(pdf["url"], pdf["month"])
        for entry in oems:
            brand_id = _oem_to_brand_id(entry["oem"])
            if not brand_id:
                continue
            key = (brand_id, pdf["month"])
            # FADA sometimes lists Bajaj twice (group + ltd); prefer the larger
            existing = rows.get(key)
            if existing and existing["units"] >= entry["units"]:
                continue
            rows[key] = {
                "brand_id": brand_id,
                "month": pdf["month"],
                "units": entry["units"],
                "source_url": pdf["url"],
            }
    print(f"[fada] parsed {len(rows)} brand-month rows from {len(pdfs)} PDFs")
    return list(rows.values())
