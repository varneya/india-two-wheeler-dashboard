"""
BikeWale catalogue scraper — populates `bike_variants` from BikeWale's
per-brand listing pages.

Each brand's `/bikewale.com/<brand>-bikes/` page embeds a window-level
`__INITIAL_STATE__` JSON with `makePage.models[]` — the canonical list of
variants currently on sale, with priceOverview, imagePath, bodyStyleId,
status, etc. We parse that JSON instead of scraping the rendered DOM
because the JSON is structured + stable across page-template tweaks.

What we extract per variant:
  - variant_id      = "<brand_id>-<modelMaskingName>" (e.g. "bajaj-pulsar-n160")
  - parent_model_id = "<brand_id>-<canonical-first-word>" (matches the
                      legacy `bikes.id` scheme so today's sales rows
                      attach without rewrites)
  - brand_id, display_name, displacement_cc, price_onroad, image_url
  - segment_id      = derived from (body_style, cc, is_electric)
  - status          = 'on_sale' | 'discontinued'

Fragility notes
  - BikeWale's bodyStyleId is integer-coded with no public mapping;
    we use it as a HINT and rely on name-pattern classification as the
    primary body-style signal.
  - cc isn't in the listing JSON; we derive from numeric tokens in the
    model name (Pulsar N160 → 160). Falls through to None for ambiguous
    names; segment assignment skips those.
"""

from __future__ import annotations

import json
import re
import time

import requests

import bike_catalogue


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Brand slugs as BikeWale uses them. Same as our internal brand_ids
# except ola-electric / ather etc. that aren't in our motorcycle
# catalogue but ARE active two-wheeler makers worth tracking.
# BikeWale slugs as they appear in the URL path. Most match our brand_id
# scheme; a few collapse-the-hyphen ("royalenfield" not "royal-enfield",
# "ola" not "ola-electric"). The mapping back to our internal brand_id
# happens via the JSON's makeMaskingName which we trust as canonical.
BRAND_SLUGS = [
    # Catalogue-aligned (legacy bike_catalogue.BRANDS keys)
    "yamaha", "honda", "hero", "bajaj", "tvs", "royalenfield",
    "suzuki", "ktm", "aprilia", "kawasaki", "harley-davidson",
    "triumph", "ducati", "bmw", "husqvarna",
    # Indian-market additions outside the legacy catalogue
    "jawa", "yezdi", "bsa",
    "ola", "ather", "ultraviolette",
    "vida", "tork-motors", "bgauss",
]


# Fallback displacements for popular models whose names don't include cc.
# Keyed by lowercased model name WITHOUT the brand prefix (since
# `derive_displacement_cc` is called with just the modelName from
# BikeWale's JSON). Yamaha's R15/MT-15/FZ family is 150cc-class; Honda's
# Hornet 2.0 is 184cc; etc. Used only when the regex finds no numeric
# token in the plausible 50-2000cc range.
KNOWN_DISPLACEMENTS: dict[str, int] = {
    # Yamaha 150cc class
    "r15": 155, "r15 v4": 155, "r15s": 155, "r15 s": 155,
    "mt 15": 155, "mt-15": 155, "mt 15 v2": 155,
    "fz": 149, "fz s": 149, "fz s fi": 149, "fz fi": 149, "fzs fi v4": 149,
    "fz x": 149, "fz x hybrid": 149, "fz s hybrid": 149, "fz rave": 149,
    # Yamaha 600-900cc imports
    "mt-07": 689, "yzf-r7": 689,
    "mt-09": 890, "yzf r9": 890, "r9": 890,
    # Honda
    "unicorn": 162, "shine": 125, "livo": 110,
    "hornet": 184, "hornet 2.0": 184,
    "goldwing": 1833, "goldwing tour": 1833,
    # TVS
    "ronin": 225, "sport": 110, "radeon": 110,
    "star city": 110, "star city plus": 110,
    "apache rtx": 300,
    # Misc
    "freedom": 125,
}


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def _extract_initial_state(html: str) -> dict | None:
    """Pull the `window.__INITIAL_STATE__ = {…}` JSON out of the page.
    Uses a brace-balanced scan rather than regex because the JSON
    contains nested braces in string fields."""
    needle = "window.__INITIAL_STATE__ = "
    i = html.find(needle)
    if i < 0:
        return None
    start = i + len(needle)
    depth = 0
    in_str = False
    esc = False
    for j in range(start, len(html)):
        c = html[j]
        if esc:
            esc = False
            continue
        if in_str:
            if c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:j + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _fetch_brand_page(brand_slug: str) -> str | None:
    url = f"https://www.bikewale.com/{brand_slug}-bikes/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        return r.text
    except requests.RequestException as e:
        print(f"[bikewale] {brand_slug}: fetch failed {e}")
        return None


# ---------------------------------------------------------------------------
# Heuristics: cc, body style, parent model
# ---------------------------------------------------------------------------

def derive_displacement_cc(model_name: str) -> int | None:
    """Pull the most-likely displacement from a model name.
    'Pulsar N160' → 160; 'Pulsar NS200' → 200; 'Pulsar 220 F' → 220;
    'CT 100' → 100; 'Pulsar RS 200' → 200; 'Classic 350' → 350.

    Uses non-digit lookarounds (not word-boundaries) because letters +
    digits sit in the same word ('N160' has no \\b between 'N' and '1').
    Returns None for ambiguous names with no numeric token."""
    name = model_name.replace("[", " ").replace("]", " ")
    # Drop year tokens (e.g. "2024-2026") — they aren't displacements
    name = re.sub(r"(?<!\d)(?:19|20)\d{2}(?:-\d{4})?(?!\d)", "", name)
    # Numeric tokens of 2-4 digits with non-digit boundaries
    nums = [int(m) for m in re.findall(r"(?<!\d)(\d{2,4})(?!\d)", name)]
    plausible = [n for n in nums if 50 <= n <= 2000]
    if plausible:
        # When multiple numbers appear (e.g. "RTR 200 4V" or "Apache RR 310"),
        # the largest is almost always the displacement.
        return max(plausible)
    # No numeric token in the plausible range — try the lookup table for
    # well-known models (R15, MT-15, FZ, Hornet, Goldwing, etc.).
    return KNOWN_DISPLACEMENTS.get(model_name.lower())


# Slug/name patterns → body style. Order matters — most-specific first.
# `body_style_id` is BikeWale's internal coding; we use it as a tiebreaker
# only because the int → label map isn't published.
_BODY_STYLE_PATTERNS = [
    # Adventure / ADV — tested first, before modern-classic, since
    # Himalayan/Scrambler are ADVs by frame (and "scrambler" alone
    # below would catch them as modern-classic otherwise).
    (re.compile(r"\bhimalayan|tiger 660|tiger 900|africa twin|v-strom|versys|adv\b|tenere|nx500|nx200|crf|cb500x|cb200x|xpulse|xtreme.*200|ducati desertx|scram\s*411|scrambler 400 x|pan america\b", re.I), "adventure"),
    # Cruiser
    (re.compile(r"\bavenger|cruise|meteor|shotgun|interceptor.*650|bullet|hayabusa|sportster|fat boy|street bob|softail|low rider|chief\b", re.I), "cruiser"),
    # Modern classic / retro
    (re.compile(r"\bclassic|hunter 350|bonneville|speedmaster|street twin|t100|t120|w800|cafe racer|continental gt|thruxton|flying flea|guerrilla\b", re.I), "modern-classic"),
    # Sport (full fairing)
    (re.compile(r"\b(?:rs(?:\s|$)|rs\s?\d{3}|r15|r3|r7|r9|r1\b|rc[\s-]?(?:125|200|250|390|490)|ninja|panigale|streetfighter|gixxer\s*sf|cbr|yzf-r|cb1000gt|apache\s*rr|gsx-?r)", re.I), "sports"),
    # Naked / streetfighter
    (re.compile(r"\b(?:naked|duke|monster|street triple|trident|tiger 850|z\s?\d{3,4}|mt[\s-]\d|pulsar\s*n\d|pulsar\s*ns|n\d{3}|dominar|svartpilen|vitpilen|brutale|tuono|hornet|cb\d{3}f?\b|cb\d{4}r|gixxer(?!\s*sf)|fz|raider|apache rtr|xtreme(?!\s*200))", re.I), "naked"),
    # Off-road / dirt
    (re.compile(r"\bxr\d{3}|crf\d{3}l|crf\d{3} rally|enduro|sx-?f|exc\b", re.I), "off-road"),
    # Mopeds
    (re.compile(r"\bxl[\s-]?(?:100|super)|moped|tvs xl\b", re.I), "moped"),
    # Premium commuter (executive segment)
    (re.compile(r"\bglamour|hornet 2\.0|unicorn|sp[\s-]125|shine|achiever|pulsar 150|pulsar 180|pulsar 220\b", re.I), "commuter"),
    # Basic commuter
    (re.compile(r"\bsplendor|hf deluxe|hf 100|passion|destini|joy|cd[\s-]?dawn|platina|ct[\s-]?\d|caliber|boxer|cd 110|livo|dream|sport\b|radeon|star city|freedom\b", re.I), "commuter"),
]


def classify_body_style(
    model_name: str,
    body_style_id: int | None,
    is_electric: bool,
    fuel_hint: str | None = None,
) -> str:
    """Return one of: commuter | sports | naked | modern-classic | adventure |
    cruiser | scooter | e-scooter | e-bike | moped | off-road | unknown."""
    name_lc = model_name.lower()

    # Electric branch first — treats Chetak / iQube / Vida as e-scooter
    # regardless of legacy model branding.
    if is_electric:
        if any(s in name_lc for s in ("scooter", "chetak", "iqube", "vida", "ola s", "ather", "rizta")):
            return "e-scooter"
        # Default electric to e-bike if it's not obviously a scooter
        return "e-bike"

    # bodyStyleId == 5 in BikeWale's coding maps to scooter on the
    # examples we sampled (Chetak, scooter listings).
    if body_style_id == 5:
        return "scooter"
    # Common scooter giveaways in the name
    if any(k in name_lc for k in (
        "activa", "jupiter", "ntorq", "fascino", "rayzr", "dio",
        "burgman", "aerox", "access", "destini", "pleasure",
        "grazia", "zest", "pep", "wego", "scooty", "let's", "lets",
    )):
        return "scooter"

    for pat, body in _BODY_STYLE_PATTERNS:
        if pat.search(name_lc):
            return body

    # bodyStyleId fallback — 3 is consistently naked in samples,
    # 1 is cruiser, 0 is generic commuter
    if body_style_id == 3:
        return "naked"
    if body_style_id == 1:
        return "cruiser"
    if body_style_id == 0:
        return "commuter"

    return "unknown"


def assign_segment(body_style: str, cc: int | None, is_electric: bool) -> str | None:
    """Map a (body_style, cc) pair to a segment_id. Mirrors the segments
    seeded in database._SEGMENT_SEED. Returns None when the pair doesn't
    fit any segment so the row is still stored (just unsegmented)."""
    if is_electric:
        # All electric two-wheelers fall into one of two buckets — we
        # don't slice them by cc since most are direct-drive.
        if body_style in ("e-scooter", "scooter"):
            return "e-scooter"
        return "e-bike"

    if body_style == "scooter":
        if cc is None:
            return "scooter-100-125"
        return "scooter-100-125" if cc <= 125 else "scooter-125-200"

    if body_style == "moped":
        return "moped"

    if cc is None:
        return None  # need a number to bucket motorcycles

    if body_style == "commuter":
        if cc <= 125: return "commuter-100-125"
        if cc <= 150: return "commuter-125-150"
        return "commuter-premium-150-200"
    if body_style == "sports":
        if cc <= 300: return "sports-150-300"
        if cc <= 500: return "sports-300-500"
        return "sports-500+"
    if body_style == "naked":
        if cc <= 300: return "naked-150-300"
        if cc <= 500: return "naked-300-500"
        return "naked-500+"
    if body_style == "modern-classic":
        if cc <= 400: return "modern-classic-350"
        return "modern-classic-500+"
    if body_style == "adventure":
        if cc <= 400: return "adventure-200-400"
        return "adventure-500+"
    if body_style == "cruiser":
        if cc <= 300: return "cruiser-150-300"
        return "cruiser-350+"

    return None


def derive_parent_model_id(brand_id: str, model_name: str) -> str:
    """Compute a parent_model_id that matches the legacy `bikes.id` scheme
    (e.g. 'bajaj-pulsar' for any Pulsar variant). First, try matching the
    name against the curated bike_catalogue (which already knows that
    'Pulsar N160' rolls up to 'Pulsar'). Fall back to a 'first-word'
    heuristic when the catalogue doesn't have the brand."""
    if brand_id in bike_catalogue.CATALOGUE:
        entry = bike_catalogue.find_model(brand_id, model_name)
        if entry:
            return bike_catalogue.make_bike_id(brand_id, entry["canonical"])

    # Fallback — strip trailing variant tokens (numbers + size suffixes)
    # and lowercase. "Avenger Street 220" → "avenger".
    base = re.sub(r"\s+", " ", model_name).strip()
    base = re.sub(r"\b(?:[A-Z]+\d+|RS|N|NS|RTR|R|F)\b\s*$", "", base, flags=re.IGNORECASE).strip()
    # Take everything up to the first digit token (Pulsar N160 → Pulsar)
    base = re.split(r"\s+\d", base, maxsplit=1)[0].strip()
    if not base:
        base = model_name.split()[0]
    slug = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")
    return f"{brand_id}-{slug}" if not slug.startswith(f"{brand_id}-") else slug


# ---------------------------------------------------------------------------
# Top-level scrape
# ---------------------------------------------------------------------------

def scrape_brand(brand_slug: str) -> list[dict]:
    """Return [{variant fields}] for every active variant of a brand.
    Empty list if the page can't be fetched or the JSON shape changed."""
    html = _fetch_brand_page(brand_slug)
    if not html:
        return []
    state = _extract_initial_state(html)
    if not state:
        print(f"[bikewale] {brand_slug}: __INITIAL_STATE__ not found")
        return []
    page = state.get("makePage") or {}
    models = page.get("models") or []
    if not models:
        print(f"[bikewale] {brand_slug}: empty models[]")
        return []

    out: list[dict] = []
    for m in models:
        try:
            mask = m.get("modelMaskingName")
            name = m.get("modelName")
            if not (mask and name):
                continue
            brand_mask = m.get("makeMaskingName") or brand_slug
            cc = derive_displacement_cc(name)
            is_elec = bool(m.get("isElectricVehicle"))
            body = classify_body_style(name, m.get("bodyStyleId"), is_elec)
            seg = assign_segment(body, cc, is_elec)
            parent = derive_parent_model_id(brand_mask, name)
            price = (m.get("priceOverview") or {}).get("price") or None
            img_path = m.get("imagePath") or ""
            image_url = f"https://imgd.aeplcdn.com/664x374{img_path}" if img_path else None
            launched = m.get("launchedOn") or ""
            launch_year = None
            mlaunch = re.search(r"(?:19|20)\d{2}", launched)
            if mlaunch:
                try:
                    launch_year = int(mlaunch.group(0))
                except ValueError:
                    pass
            out.append({
                "variant_id": f"{brand_mask}-{mask}",
                "parent_model_id": parent,
                "brand_id": brand_mask,
                "segment_id": seg,
                "display_name": f"{m.get('makeName')} {name}".strip(),
                "displacement_cc": cc,
                "price_onroad": int(price) if price else None,
                "bikewale_slug": f"{brand_mask}-bikes/{mask}",
                "image_url": image_url,
                "status": "on_sale",
                "launch_year": launch_year,
            })
        except Exception as e:
            print(f"[bikewale] {brand_slug}: model parse failed: {e}")
    return out


def scrape_all() -> list[dict]:
    """Top-level: walk BRAND_SLUGS, scrape each brand's listing, return
    a flat list of variant dicts ready for upsert. ~13-25 brands × ~25
    models each ~ 200-500 variants total."""
    all_variants: list[dict] = []
    for slug in BRAND_SLUGS:
        rows = scrape_brand(slug)
        all_variants.extend(rows)
        print(f"[bikewale] {slug}: {len(rows)} variants")
        # Polite delay between brands — BikeWale isn't aggressively
        # rate-limiting at single-brand-page scale, but we don't want
        # to look like a scraper either.
        time.sleep(0.5)
    print(f"[bikewale] total: {len(all_variants)} variants across {len(BRAND_SLUGS)} brands")
    return all_variants
