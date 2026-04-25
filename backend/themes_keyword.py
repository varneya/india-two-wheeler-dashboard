"""
Option 1 — Rule-based keyword theme extraction.
No ML, no API. Fast, deterministic, transparent.

Buckets cover both motorcycles and scooters. Bike-class-irrelevant buckets
will simply have low mention counts on the wrong class (e.g. "Storage &
Practicality" rarely fires on a sport bike review), so we don't need to
swap entire bucket sets per bike — just include keywords for both.
"""

import re
from collections import defaultdict

# Theme buckets (motorcycle + scooter keywords merged)
THEME_KEYWORDS = {
    "Engine & Performance": [
        "engine", "power", "rpm", "torque", "acceleration", "speed", "cc",
        "smooth", "responsive", "rev", "throttle", "horsepower", "bhp",
        "performance", "punchy", "quick", "fast", "slow", "lethargic",
        "pickup",  # scooter-friendly term
    ],
    "Comfort & Ergonomics": [
        "comfort", "comfortable", "seat", "ergonomic", "posture", "riding position",
        "back", "backache", "backpain", "fatigue", "pillion", "long ride", "highway",
        "handlebar", "footpeg", "reach", "height", "tall", "short",
        "cushion", "floorboard", "leg room", "legroom",
    ],
    "Suspension & Handling": [
        "suspension", "handling", "cornering", "agile", "stable", "chassis",
        "fork", "shock", "absorber", "manoeuvr", "maneuver", "turn", "nimble", "stiff",
        "bumpy", "pothole", "rough road", "city", "twisties", "lean", "balanced",
    ],
    "Design & Styling": [
        "design", "retro", "look", "style", "colour", "color", "finish",
        "neo-retro", "classic", "aesthetic", "beautiful", "attractive", "vintage",
        "headlight", "tail", "instrument", "cluster", "body", "silhouette",
        "premium look", "graphics",
    ],
    "Mileage & Fuel Economy": [
        "mileage", "fuel", "kmpl", "economy", "efficiency", "tank",
        "range", "consumption", "petrol", "fill", "litre", "liter",
    ],
    "Value & Price": [
        "price", "value", "money", "expensive", "affordable", "cost",
        "worth", "budget", "premium", "pricing", "rupee", "lakh",
        "overpriced", "competitive", "bang for", "vfm",
    ],
    "Build Quality & Fit-Finish": [
        "build", "quality", "fit", "finish", "plastic", "metal",
        "panel", "switch", "material", "sturdy", "solid", "rattl",
        "vibrat", "gap", "paint", "chrome", "creak",
    ],
    "Braking": [
        "brake", "braking", "abs", "stopping", "disc", "sinter",
        "bite", "fade", "lever", "anchors", "cbs",
    ],
    "Features & Tech": [
        "feature", "bluetooth", "usb", "charging", "digital", "analog",
        "instrument", "traction", "mode", "led", "assist", "quickshifter",
        "technology", "connected", "navigation", "smart key", "tft",
    ],
    # ---- Scooter-leaning buckets (rarely fire on motorcycle reviews) ----
    "Storage & Practicality": [
        "storage", "boot", "boot space", "underseat", "under-seat", "compartment",
        "helmet", "luggage", "groceries", "shopping", "hook", "glovebox",
    ],
    "Daily Commute & Family": [
        "daily commute", "office", "everyday", "family", "wife", "kids",
        "school", "scooter for", "city ride", "errands", "easy to ride",
        "lightweight", "nimble in traffic",
    ],
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.!?\n]", text) if len(s.strip()) > 20]


def get_default_keywords() -> dict[str, list[str]]:
    """Return a deep copy of the default theme→keywords mapping."""
    return {theme: list(kws) for theme, kws in THEME_KEYWORDS.items()}


def analyze(
    reviews: list[dict],
    custom_keywords: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Bucket reviews into themes by keyword matching.

    `custom_keywords` (theme → [keyword, …]) — if provided, these REPLACE the
    default `THEME_KEYWORDS` for the duration of this call. Empty buckets
    (e.g. user removed all keywords) are skipped. Buckets that aren't in the
    override dict still use defaults — pass an explicit empty list to disable.
    """
    keywords_map = custom_keywords if custom_keywords else THEME_KEYWORDS

    texts = [r["review_text"] for r in reviews if r.get("review_text")]
    theme_mentions: dict[str, list[str]] = defaultdict(list)

    for text in texts:
        lower = text.lower()
        for theme, keywords in keywords_map.items():
            if not keywords:
                continue
            for kw in keywords:
                kw_lc = kw.lower()
                if not kw_lc:
                    continue
                if kw_lc in lower:
                    for sent in _sentences(text):
                        if kw_lc in sent.lower():
                            theme_mentions[theme].append(sent)
                    break  # one match per review per theme is enough

    results = []
    for theme, snippets in sorted(theme_mentions.items(), key=lambda x: -len(x[1])):
        pos_words = ["good", "great", "excellent", "smooth", "love", "amazing",
                     "best", "fantastic", "brilliant", "happy", "perfect", "solid"]
        neg_words = ["bad", "poor", "issue", "problem", "disappoint", "worst",
                     "terrible", "awful", "hate", "fail", "lacking", "stiff"]

        all_text = " ".join(snippets).lower()
        pos = sum(all_text.count(w) for w in pos_words)
        neg = sum(all_text.count(w) for w in neg_words)

        if pos > neg * 2:
            sentiment = "positive"
        elif neg > pos * 2:
            sentiment = "negative"
        else:
            sentiment = "mixed"

        # Surface the actual keyword list used (custom > default), capped at 6
        used = keywords_map.get(theme) or THEME_KEYWORDS.get(theme, [])
        results.append({
            "name": theme,
            "sentiment": sentiment,
            "mention_count": len(snippets),
            "example_quotes": snippets[:3],
            "keywords": used[:6],
        })

    return results
