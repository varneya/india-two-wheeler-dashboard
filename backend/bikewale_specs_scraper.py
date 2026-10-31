"""
BikeWale per-variant tech-specs scraper.

For every row in `bike_variants`, fetches the model's BikeWale page (the
same URL the catalogue scraper already hits) and parses the
`__INITIAL_STATE__.modelPage.specifications` + `.features` branches into a
categorised payload. Derives ~25 normalized columns from the raw values
and writes both to `bike_specs`.

Why model-page-not-/specs-features/:
  The dedicated /specs-features/ subpath returns 404 on BikeWale today.
  The main model page embeds the full spec/feature payload in its
  `__INITIAL_STATE__` JSON — same shape, no extra request.

Variant granularity:
  Inside one BikeWale model page, `versions[]` lists color/edition
  sub-variants whose `specsSummary` is identical (mechanically the same
  bike). So we store one row per `bike_variants.variant_id`, since each
  variant in our DB corresponds to one BikeWale model page.
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

import requests

from bikewale_catalogue import HEADERS, _extract_initial_state
import database


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

BIKEWALE_BASE = "https://www.bikewale.com"


def fetch_model_page(bikewale_slug: str) -> tuple[str, dict | None]:
    """Returns (url, parsed_initial_state_json or None).
    bikewale_slug is the path fragment stored in bike_variants, e.g.
    'yamaha-bikes/r15' or 'bajaj-bikes/pulsar-n160'."""
    url = f"{BIKEWALE_BASE}/{bikewale_slug.strip('/')}/"
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        if r.status_code != 200:
            return url, None
        return url, _extract_initial_state(r.text)
    except requests.RequestException:
        return url, None


# ---------------------------------------------------------------------------
# Raw payload extraction
# ---------------------------------------------------------------------------

def extract_categorised(model_page: dict) -> dict[str, dict[str, dict]]:
    """Build the categorised spec payload that lands in raw_specs_json.

    Returns a nested dict shaped like:
      {
        "Power & Performance": {
          "Displacement": {"value": "155", "unit": "cc"},
          "Max Power":    {"value": "18.1 bhp @ 10000 rpm", "unit": ""},
          ...
        },
        "Brakes & Wheels": {...},
        ...
        "Instrument Cluster": {...},   # feature categories included
        ...
      }
    Items whose `values[0]` is empty/missing are skipped — keeps the JSON
    payload focused on what BikeWale actually populated for the bike.
    """
    out: dict[str, dict[str, dict]] = {}
    for branch in ("specifications", "features"):
        for cat in model_page.get(branch, []) or []:
            cat_name = (cat.get("name") or "").strip()
            if not cat_name:
                continue
            bucket: dict[str, dict] = {}
            for item in cat.get("items", []) or []:
                name = (item.get("name") or "").strip()
                if not name:
                    continue
                vals = item.get("values") or []
                if not vals:
                    continue
                raw_val = vals[0]
                if raw_val is None or raw_val == "":
                    continue
                bucket[name] = {
                    "value": str(raw_val).strip(),
                    "unit": (item.get("unitType") or "").strip(),
                }
            if bucket:
                out[cat_name] = bucket
    return out


# ---------------------------------------------------------------------------
# Typed-column derivation
# ---------------------------------------------------------------------------

def _num(s: str) -> float | None:
    """First decimal number in s (e.g. '18.1 bhp @ 10000 rpm' → 18.1).
    Returns None if no number found."""
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _int(s: str) -> int | None:
    n = _num(s)
    return int(n) if n is not None else None


def _classify_cooling(text: str) -> str | None:
    t = text.lower()
    if "liquid" in t:
        return "liquid"
    if "oil" in t and "cool" in t:
        return "oil"
    if "air" in t:
        return "air"
    return None


def _classify_starter(text: str) -> str | None:
    t = text.lower()
    has_self = any(k in t for k in ("self", "electric"))
    has_kick = "kick" in t
    if has_self and has_kick:
        return "both"
    if has_self:
        return "electric"
    if has_kick:
        return "kick"
    return None


def _classify_fuel_system(text: str) -> str | None:
    t = text.lower()
    if "fi" in t or "injection" in t or "efi" in t or "pgm" in t:
        return "fi"
    if "carb" in t:
        return "carb"
    return None


def _classify_abs(text: str) -> str | None:
    t = text.lower()
    if "dual" in t:
        return "dual"
    if "single" in t:
        return "single"
    if "cbs" in t or "combi" in t:
        return "cbs"
    if t in ("", "no", "none", "false"):
        return None
    if "yes" in t or "abs" in t:
        return "single"
    return None


def _parse_brake(text: str) -> tuple[str | None, int | None]:
    """'Disc, 282 mm, 2 piston caliper' -> ('disc', 282).
    'Disc, 2 piston caliper'           -> ('disc', None).
    'Drum, 130 mm'                     -> ('drum', None).  (disc_mm is only
        populated for disc brakes — drum size lives in raw_specs_json.)
    Requires an explicit `<n> mm` token so the piston count in strings
    like 'Disc, 2 piston caliper' doesn't get misread as disc diameter."""
    if not text:
        return None, None
    t = text.lower()
    brake_type = None
    if "disc" in t:
        brake_type = "disc"
    elif "drum" in t:
        brake_type = "drum"
    disc_mm = None
    if brake_type == "disc":
        m = re.search(r"(\d+)\s*mm\b", text, re.I)
        if m:
            disc_mm = int(m.group(1))
    return brake_type, disc_mm


def _parse_engine_type(text: str) -> tuple[int | None, str | None]:
    """'1 Cylinder, Liquid Cooled, 4 Valves' -> (cylinders=1, cooling='liquid').
    'Single Cylinder, Air Cooled' -> (1, 'air')."""
    if not text:
        return None, None
    t = text.lower()
    cyl = None
    if "single" in t:
        cyl = 1
    else:
        m = re.search(r"(\d+)\s*cyl", t)
        if m:
            cyl = int(m.group(1))
    return cyl, _classify_cooling(text)


def _parse_transmission(text: str) -> tuple[str | None, int | None]:
    """'6 Speed Manual' -> ('6 Speed Manual', 6); 'CVT' -> ('CVT', None)."""
    if not text:
        return None, None
    gears = None
    m = re.search(r"(\d+)\s*speed", text, re.I)
    if m:
        gears = int(m.group(1))
    return text.strip(), gears


def _parse_dims(text: str) -> tuple[int | None, int | None, int | None]:
    """'1990 mm x 725 mm x 1135 mm' -> (1990, 725, 1135).
    Handles 'x' or '×' or 'X' separators."""
    if not text:
        return None, None, None
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if len(nums) >= 3:
        return nums[0], nums[1], nums[2]
    return None, None, None


def _parse_power_or_torque(text: str) -> tuple[float | None, int | None]:
    """'18.1 bhp @ 10000 rpm' -> (18.1, 10000); '14.2 Nm @ 7500 rpm' -> (14.2, 7500).
    Returns (magnitude, rpm) — both None if the string doesn't parse."""
    if not text:
        return None, None
    m_mag = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:bhp|nm|kw|ps|hp)", text, re.I)
    m_rpm = re.search(r"@\s*(\d+)\s*rpm", text, re.I)
    mag = float(m_mag.group(1)) if m_mag else _num(text)
    rpm = int(m_rpm.group(1)) if m_rpm else None
    return mag, rpm


def derive_typed(categorised: dict[str, dict[str, dict]]) -> dict[str, Any]:
    """Walk the categorised payload and produce the ~25 typed columns.
    Lookup is by category name + field name to avoid ambiguity (e.g.
    'Front Brake' lives under 'Brakes & Wheels' both in specs and the
    nominal feature listings)."""
    def g(cat: str, field: str) -> str:
        return categorised.get(cat, {}).get(field, {}).get("value", "")

    typed: dict[str, Any] = {}

    # ---- Engine
    typed["engine_cc"] = _int(g("Power & Performance", "Displacement"))
    pwr_mag, pwr_rpm = _parse_power_or_torque(
        g("Power & Performance", "Max Power")
        or g("Power & Performance", "Max Power(bhp)")
    )
    typed["max_power_bhp"] = pwr_mag
    typed["max_power_rpm"] = pwr_rpm
    trq_mag, trq_rpm = _parse_power_or_torque(g("Power & Performance", "Max Torque"))
    typed["max_torque_nm"] = trq_mag
    typed["max_torque_rpm"] = trq_rpm

    cyl, cool = _parse_engine_type(g("Power & Performance", "Engine Type"))
    typed["cylinders"] = cyl
    typed["cooling"] = cool

    typed["fuel_system"] = _classify_fuel_system(
        g("Power & Performance", "Fuel System")
        or g("Power & Performance", "Fuel Delivery System")
        or g("Power & Performance", "Engine Type")
    )

    txn, gears = _parse_transmission(g("Power & Performance", "Transmission"))
    typed["transmission"] = txn
    typed["gears"] = gears

    typed["starter"] = _classify_starter(
        g("Safety & Convenience", "Start Type")
        or g("Power & Performance", "Starting")
    )
    typed["emission_standard"] = g("Power & Performance", "Emission Standard") or None
    typed["fuel_type"] = g("Power & Performance", "Fuel Type") or None

    # ---- Performance
    typed["mileage_kmpl"] = _num(
        g("Power & Performance", "Mileage - ARAI")
        or g("Power & Performance", "Mileage - Owner Reported")
    )
    typed["top_speed_kmph"] = _num(g("Power & Performance", "Top Speed"))
    typed["fuel_tank_l"] = _num(g("Dimensions", "Fuel Tank Capacity"))

    # ---- Dimensions
    typed["kerb_weight_kg"] = _num(g("Dimensions", "Kerb Weight"))
    typed["seat_height_mm"] = _int(g("Dimensions", "Seat Height"))
    typed["ground_clearance_mm"] = _int(g("Dimensions", "Ground Clearance"))
    typed["wheelbase_mm"] = _int(g("Dimensions", "Wheelbase"))
    L, W, H = _parse_dims(g("Dimensions", "Overall Dimensions (LxWxH)"))
    typed["length_mm"] = L
    typed["width_mm"] = W
    typed["height_mm"] = H

    # ---- Brakes / ABS
    fb_type, fb_disc = _parse_brake(g("Brakes & Wheels", "Front Brake"))
    typed["front_brake_type"] = fb_type
    typed["front_brake_disc_mm"] = fb_disc
    rb_type, rb_disc = _parse_brake(g("Brakes & Wheels", "Rear Brake"))
    typed["rear_brake_type"] = rb_type
    typed["rear_brake_disc_mm"] = rb_disc
    typed["abs_type"] = _classify_abs(
        g("Brakes & Wheels", "Braking System")
        or g("Brakes & Wheels", "ABS")
        or g("Safety & Convenience", "Antilock Braking System")
    )

    # Drop None-only entries → keeps NULL semantics in SQLite explicit
    return {k: v for k, v in typed.items() if v is not None}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def scrape_variant(variant_id: str, bikewale_slug: str) -> dict | None:
    """Fetch + parse one variant. Returns the result dict (typed +
    raw_categorised + url), or None if the page failed to fetch / parse.
    Does NOT write to the DB — caller does that, so the function is easy
    to test in isolation."""
    url, state = fetch_model_page(bikewale_slug)
    if not state:
        return None
    model_page = state.get("modelPage") or {}
    if not model_page:
        return None
    categorised = extract_categorised(model_page)
    if not categorised:
        return None
    typed = derive_typed(categorised)
    return {
        "url": url,
        "typed": typed,
        "categorised": categorised,
    }


def refresh_all_specs(
    limit: int | None = None,
    sleep_min: float = 1.0,
    sleep_max: float = 2.0,
    verbose: bool = True,
) -> dict:
    """Iterate every on-sale variant, scrape its BikeWale page, and upsert
    bike_specs. Returns a {ok, failed, skipped} count summary."""
    variants = database.list_variants(on_sale_only=True)
    if limit:
        variants = variants[:limit]

    ok = failed = skipped = 0
    for i, v in enumerate(variants, 1):
        vid = v["variant_id"]
        slug = v["bikewale_slug"]
        if not slug:
            skipped += 1
            continue

        result = scrape_variant(vid, slug)
        if not result:
            failed += 1
            if verbose:
                print(f"[specs] {i}/{len(variants)} {vid}: FAILED")
            time.sleep(random.uniform(sleep_min, sleep_max))
            continue

        database.upsert_bike_spec(
            variant_id=vid,
            source="bikewale",
            source_url=result["url"],
            typed=result["typed"],
            raw_specs_json=json.dumps(result["categorised"], ensure_ascii=False),
        )
        ok += 1
        if verbose:
            t = result["typed"]
            print(f"[specs] {i}/{len(variants)} {vid}: cc={t.get('engine_cc')} "
                  f"bhp={t.get('max_power_bhp')} kg={t.get('kerb_weight_kg')} "
                  f"abs={t.get('abs_type')}")
        time.sleep(random.uniform(sleep_min, sleep_max))

    return {"ok": ok, "failed": failed, "skipped": skipped}


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else None
    summary = refresh_all_specs(limit=n)
    print(f"\n[specs] done: {summary}")
