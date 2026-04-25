"""
Bike registry — auto-discovery + parsing.

Turns RushLane "sales breakup" article text into structured
(brand, model, units) rows, and helps build the bikes catalogue.
"""

from __future__ import annotations

import re
import requests as http_requests

import bike_catalogue

# Manufacturers we look for in RushLane URLs and article prose. Driven
# from the catalogue file so changes only need to happen in one place.
BRANDS = list(bike_catalogue.BRANDS.keys())

# Pretty-cased version for display
BRAND_DISPLAY = {bid: meta["display"] for bid, meta in bike_catalogue.BRANDS.items()}

# Phrases that look like a model but aren't real bikes
NON_MODELS = {
    "total", "total sales", "total domestic", "total exports",
    "domestic", "exports", "two wheeler", "two-wheeler",
    "scooter", "scooters", "motorcycle", "motorcycles",
    "ytd", "month", "year", "growth", "decline", "share",
    "sales", "unit sales", "units", "register", "registered",
    "report", "report card", "breakup", "yoy", "mom",
    "fy", "q1", "q2", "q3", "q4", "h1", "h2",
    "ago", "compared", "compared to", "vs", "comparison",
    "top", "best", "worst", "rise", "fall", "drop", "increase",
    "decrease", "previous month", "last month", "this month",
    "and", "the", "with", "from", "than", "which",
    "demand", "outlook", "performance", "production",
    # Months (RushLane often writes "March 2026 - ... units")
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec",
    # Sentence-fragment giveaways
    "one", "two", "three", "first", "second", "third",
    "biggest", "highlight", "highlights", "strong", "stable",
    "steadily", "massive", "modest", "robust",
    "in march", "in april",
}

# Words inside the model phrase that prove it's actually a sentence fragment
SENTENCE_WORDS = {
    "registered", "contributed", "maintained", "recorded",
    "with", "and", "of", "also", "highlights", "biggest",
    "growth", "volumes", "stable", "strong", "steadily", "massive",
    "the", "in", "at", "by", "to", "from", "was", "were",
    "added", "posted", "reached", "achieved", "saw", "showed",
}

# Common bike model -> brand inference (used when article doesn't include brand)
MODEL_BRAND_HINTS = {
    "fz": "yamaha", "r15": "yamaha", "mt": "yamaha", "mt-15": "yamaha",
    "mt 15": "yamaha", "rayzr": "yamaha", "fascino": "yamaha",
    "aerox": "yamaha", "xsr": "yamaha", "xsr 155": "yamaha", "r3": "yamaha",
    "shine": "honda", "activa": "honda", "unicorn": "honda", "dio": "honda",
    "sp 125": "honda", "sp125": "honda", "hornet": "honda",
    "splendor": "hero", "passion": "hero", "glamour": "hero", "destini": "hero",
    "xpulse": "hero", "xtreme": "hero", "hf": "hero", "karizma": "hero",
    "pulsar": "bajaj", "platina": "bajaj", "avenger": "bajaj",
    "dominar": "bajaj", "ct": "bajaj", "chetak": "bajaj",
    "apache": "tvs", "jupiter": "tvs", "ntorq": "tvs",
    "raider": "tvs", "ronin": "tvs", "iqube": "tvs", "xl": "tvs",
    "classic": "royal-enfield", "bullet": "royal-enfield",
    "meteor": "royal-enfield", "himalayan": "royal-enfield",
    "interceptor": "royal-enfield", "continental": "royal-enfield",
    "hunter": "royal-enfield", "guerrilla": "royal-enfield",
    "shotgun": "royal-enfield",
    "access": "suzuki", "burgman": "suzuki", "gixxer": "suzuki",
    "v-strom": "suzuki", "hayabusa": "suzuki", "avenis": "suzuki",
    "duke": "ktm", "rc": "ktm", "adventure": "ktm",
    "sx-r": "aprilia", "sxr": "aprilia", "tuono": "aprilia",
    "rs 457": "aprilia", "rs457": "aprilia",
    "ninja": "kawasaki", "z650": "kawasaki", "z900": "kawasaki",
    "vulcan": "kawasaki", "versys": "kawasaki",
}


# ---------------------------------------------------------------------------
# Brand detection
# ---------------------------------------------------------------------------

_BRAND_URL_RE = re.compile(
    r"rushlane\.com/(" + "|".join(re.escape(b) for b in BRANDS) + r")-",
    re.IGNORECASE,
)


def brand_from_url(url: str) -> str | None:
    m = _BRAND_URL_RE.search(url)
    return m.group(1).lower() if m else None


def infer_brand_from_model(model: str) -> str | None:
    lo = model.lower().strip()
    for hint, brand in MODEL_BRAND_HINTS.items():
        if hint in lo:
            return brand
    return None


# ---------------------------------------------------------------------------
# Parsing article text into (model, units) rows
# ---------------------------------------------------------------------------

# Tokens we want to drop when slicing the URL slug for model names.
# Anything that's a brand name, a month/year, or a marketing word.
URL_DROP_TOKENS = (
    set(BRANDS)
    | {"sales", "breakup", "india", "report", "card", "monthly",
       "domestic", "exports", "performance", "growth", "ytd",
       "becomes", "top", "seller", "now", "accounts", "for", "of",
       "total", "sales", "registered", "with"}
    | set(MONTH_NAMES_LIST := [
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
        "sep", "sept", "oct", "nov", "dec", "january", "february",
        "march", "april", "june", "july", "august", "september",
        "october", "november", "december",
    ])
)


def _strip_article_id(slug: str) -> str:
    # The trailing 8-9 digit article id, e.g. -12544753.html
    return re.sub(r"-?\d{6,}\.html?$", "", slug)


def _slug_tokens(url: str) -> list[str]:
    # take last path component
    last = url.rstrip("/").split("/")[-1]
    last = _strip_article_id(last)
    # strip year tokens too (4-digit numbers that look like years)
    parts = re.split(r"-+", last)
    out = []
    for p in parts:
        pl = p.lower()
        if not pl:
            continue
        if pl in URL_DROP_TOKENS:
            continue
        if re.fullmatch(r"20\d{2}", pl):     # year
            continue
        out.append(p)
    return out


def candidate_models_from_url(url: str) -> list[str]:
    """
    Slice a RushLane URL into model name candidates.
    e.g. .../yamaha-sales-breakup-march-2026-rayzr-fz-mt15-r15-12544753.html
        -> ['rayzr', 'fz', 'mt15', 'r15']
    Adjacent tokens that look like a model + variant are merged where appropriate
    (e.g. "xsr" + "155" -> "xsr 155").
    """
    tokens = _slug_tokens(url)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        next_t = tokens[i + 1] if i + 1 < len(tokens) else None

        # If a token is purely a number AND looks like a CC variant, merge into prior
        if (out
                and re.fullmatch(r"\d{2,4}", t)
                and len(t) <= 4):
            out[-1] = f"{out[-1]} {t}"
            i += 1
            continue

        # If two tokens look like a single model split (e.g. "mt", "15") and the
        # next is short numeric, merge.
        if next_t and re.fullmatch(r"\d{2,4}", next_t):
            out.append(f"{t} {next_t}")
            i += 2
            continue

        out.append(t)
        i += 1

    # Title-case each (preserve digits): "rayzr" -> "RayZR" is too aggressive,
    # just upper-first.
    return [_pretty_model(m) for m in out if _pretty_model(m).lower() not in URL_DROP_TOKENS]


def _pretty_model(slug_word: str) -> str:
    """
    Normalise a slug-derived token into a canonical display form.
    "mt 15" / "mt15"  -> "MT 15"
    "xsr155"          -> "XSR 155"
    "rayzr"           -> "Rayzr"
    """
    # First, split runs of letters+digits into "<letters> <digits>" so e.g.
    # "xsr155" becomes "xsr 155" *before* word-by-word casing.
    expanded = re.sub(r"([A-Za-z]+)(\d+)", r"\1 \2", slug_word)
    expanded = re.sub(r"\s+", " ", expanded).strip()
    parts = expanded.split()
    out = []
    for p in parts:
        if p.isdigit():
            out.append(p)
        elif len(p) <= 3:
            out.append(p.upper())
        else:
            out.append(p[0].upper() + p[1:].lower())
    return " ".join(out)


# Pattern to find "<keyword> ... <N> units" within a short window.
# Newline is a hard sentence break in the article text we extract.
# We tolerate periods inside the window because RushLane writes lots of
# percentages like "55.03%" between the bike name and the number.
def _make_units_pattern(keyword: str) -> re.Pattern:
    kw = re.escape(keyword)
    return re.compile(
        rf"\b{kw}\b[^\n]{{0,140}}?([\d]{{1,3}}(?:,\d{{3}})+|\d{{3,6}})\s*units?\b",
        re.IGNORECASE,
    )


def _is_plausible_model(name: str) -> bool:
    n = name.strip().lower()
    if len(n) < 2:
        return False
    if n in NON_MODELS:
        return False
    words = n.split()
    # Reject any phrase containing sentence-glue words (proves it's prose)
    if any(w in SENTENCE_WORDS for w in words):
        return False
    if any(w in NON_MODELS for w in words):
        return False
    # First word must look like a model name itself
    first = words[0]
    if first in NON_MODELS or first in SENTENCE_WORDS:
        return False
    # Reject pure-number names
    if re.fullmatch(r"[\d,\s]+", n):
        return False
    # Must contain at least one letter
    if not re.search(r"[a-z]", n):
        return False
    return True


def _strip_brand_prefix(model: str, brand: str | None) -> str:
    if not brand:
        return model.strip()
    pretty = BRAND_DISPLAY.get(brand, brand)
    pat = re.compile(rf"^{re.escape(pretty)}\s+", re.IGNORECASE)
    return pat.sub("", model).strip()


def parse_bikes_from_article(text: str, source_url: str,
                             brand_hint: str | None = None) -> list[dict]:
    """
    Returns [{brand, model, canonical, bike_id, bikewale_slug, keywords, units}]
    for one article.

    Strategy:
      1. Extract candidate model names from the URL slug.
      2. Match each candidate against the curated catalogue (whitelist).
         Anything not in the catalogue is rejected as a false positive.
      3. For each catalogue match, search the prose using the catalogue's
         keywords for "<keyword> ... N units" and capture the unit count.
    """
    if not text:
        return []

    detected_brand = brand_hint or brand_from_url(source_url)
    if not detected_brand:
        return []

    candidates = candidate_models_from_url(source_url)
    seen: dict[str, dict] = {}

    for cand in candidates:
        if not _is_plausible_model(cand):
            continue

        # Validate against the curated catalogue — reject anything we don't
        # recognise as a real, current/historic Indian-market model.
        entry = bike_catalogue.find_model(detected_brand, cand)
        if not entry:
            continue

        # Use the catalogue's keywords (precise) plus any extra obvious variants.
        keywords_to_try = list(entry.get("keywords") or [entry["canonical"]])
        # Also try the candidate as-written and its hyphen/space/squashed variants.
        for v in [cand, cand.replace(" ", "-"), cand.replace(" ", ""), cand.replace("-", " ")]:
            if v not in keywords_to_try:
                keywords_to_try.append(v)

        # Per-bike sanity floor — anything below this is almost certainly a
        # misparse (e.g. 125cc displacement read as a sales count).
        floor = bike_catalogue.min_units_for(entry["canonical"])
        ceiling = 200_000

        units = None
        for kw in keywords_to_try:
            if not kw:
                continue
            pat = _make_units_pattern(kw)
            m = pat.search(text)
            if m:
                try:
                    candidate_units = int(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                if floor <= candidate_units <= ceiling:
                    units = candidate_units
                    break
                # else: try the next keyword variant — this match was bogus
        if units is None:
            continue

        bike_id = bike_catalogue.make_bike_id(detected_brand, entry["canonical"])
        existing = seen.get(bike_id)
        if existing and existing["units"] >= units:
            continue
        seen[bike_id] = {
            "brand": detected_brand,
            "model": entry["canonical"],
            "canonical": entry["canonical"],
            "bike_id": bike_id,
            "bikewale_slug": entry.get("bikewale"),
            "keywords": entry.get("keywords") or [entry["canonical"]],
            "units": units,
        }

    return list(seen.values())


# ---------------------------------------------------------------------------
# Slug + keyword helpers
# ---------------------------------------------------------------------------

def slugify(brand: str, model: str) -> str:
    s = f"{brand}-{model}"
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def normalise_keywords(model: str) -> list[str]:
    """
    Build regex keywords for the extractor.
    For "XSR 155" we want both ["XSR 155", "XSR"] so prose that just says
    "XSR" still matches. We always include the full model first (most specific).
    """
    model = model.strip()
    out = [model]
    parts = model.split()
    if len(parts) > 1:
        # First word alone (e.g. "XSR", "Pulsar") if it's distinctive (>=3 chars
        # and not purely numeric)
        first = parts[0]
        if len(first) >= 3 and not first.isdigit() and first.lower() not in NON_MODELS:
            out.append(first)
    # De-dup preserving order
    seen = set()
    deduped = []
    for k in out:
        if k.lower() not in seen:
            seen.add(k.lower())
            deduped.append(k)
    return deduped


# ---------------------------------------------------------------------------
# BikeWale slug verification
# ---------------------------------------------------------------------------

_BIKEWALE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


def candidate_bikewale_slugs(brand: str, model: str) -> list[str]:
    """Generate plausible BikeWale URL slugs to probe."""
    brand_slug = brand.lower()
    model_slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    candidates = [
        f"{brand_slug}-bikes/{model_slug}",
        # Some brand names on BikeWale differ slightly (e.g. royal-enfield)
        f"{brand_slug.replace('-', '')}-bikes/{model_slug}",
    ]
    # de-dup
    seen, out = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def verify_bikewale_slug(brand: str, model: str, timeout: int = 6) -> str | None:
    """
    Probe BikeWale for a working /reviews/ URL. Returns the working slug
    (e.g. "yamaha-bikes/xsr-155") or None.
    """
    for slug in candidate_bikewale_slugs(brand, model):
        url = f"https://www.bikewale.com/{slug}/reviews/"
        try:
            r = http_requests.get(url, headers=_BIKEWALE_HEADERS,
                                  timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and "review" in r.text.lower():
                return slug
        except Exception:
            continue
    return None
