"""
YouTube transcript scraper for Indian motorcycle review channels.

For each channel in CHANNELS:
  1. yt-dlp lists the last N video IDs (no API key, just YouTube's web JSON).
  2. Each video's title + description is regex-matched against bike_catalogue.
     Videos with zero bike matches are skipped (touring vlogs, gear reviews,
     non-bike content). Comparison videos that mention multiple bikes get
     matched to all of them — that's correct, both audiences care.
  3. For matched videos, youtube-transcript-api fetches English captions.
     Bilingual channels (Auto Yogi, BikeDekho, BikeWale, JS Films) lose
     non-English videos at this step automatically.
  4. Full transcript + metadata land in `video_transcripts`; one shadow row
     per (video, bike) lands in `reviews` with source='youtube' so the
     existing themes/embeddings pipeline picks them up unchanged.

CHANNELS is a plain Python list; add a dict to extend.
"""

from __future__ import annotations

import re
import time

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        TranscriptsDisabled,
        NoTranscriptFound,
        VideoUnavailable,
    )
    YT_TRANSCRIPT_AVAILABLE = True
except ImportError:
    YT_TRANSCRIPT_AVAILABLE = False

import bike_catalogue


# ---------------------------------------------------------------------------
# Channel registry — single source of truth, extensible.
# ---------------------------------------------------------------------------
# `channel_url` is the stable yt-dlp input. Prefer the /channel/UCxxx form
# (canonical, never changes) over /@handle (changes when creators rename).
# `handle` is informational only — used in logs and as the cache key, not in
# the actual URL fetch.
# `subs_estimate`: rough size; just for logs/progress.
# Add a dict to this list to onboard a new channel — no other code change.
CHANNELS: list[dict] = [
    {"name": "Autocar India",      "handle": "@autocarindia1",     "channel_url": "https://www.youtube.com/channel/UCjWs7BxyjO5SLqevxSmp4vQ", "subs_estimate": 2_500_000},
    {"name": "PowerDrift",         "handle": "@powerdrift",        "channel_url": "https://www.youtube.com/channel/UCMDV6J2hWXet7ZCfgrXGgeg", "subs_estimate": 3_000_000},
    {"name": "MotorBeam (Faisal)", "handle": "@fasbeam",           "channel_url": "https://www.youtube.com/channel/UCPF4bAZimS4T8w1TlbeIAYg", "subs_estimate": 2_300_000},
    {"name": "Gagan Choudhary",    "handle": "@Ganikgagan",        "channel_url": "https://www.youtube.com/channel/UCA2utdbkuY6PfX0Exi2Y16w", "subs_estimate": 2_000_000},
    {"name": "Dino's Vault",       "handle": "@dinosvault",        "channel_url": "https://www.youtube.com/channel/UC-ni0xL6ILMFdzf1A2s4__A", "subs_estimate":   800_000},
    {"name": "Strell",             "handle": "@iamstrell",         "channel_url": "https://www.youtube.com/@iamstrell",                       "subs_estimate":    50_000},
    {"name": "MotorInc",           "handle": "@MotorInc",          "channel_url": "https://www.youtube.com/channel/UCO-uVs959_GUzzUx4ctwMMQ", "subs_estimate":    50_000},
    {"name": "Auto Yogi",          "handle": "@AutoYogi",          "channel_url": "https://www.youtube.com/channel/UCWlwXxozORjOVZzfGyuV6Vw", "subs_estimate":    50_000},
    {"name": "Bike with Girl",     "handle": "@BikeWithGirl",      "channel_url": "https://www.youtube.com/channel/UCiPXLJN9rn0w8jTzaSPK8iQ", "subs_estimate":    50_000},
    {"name": "BikeDekho",          "handle": "@BikeDekhoOfficial", "channel_url": "https://www.youtube.com/@BikeDekhoOfficial",               "subs_estimate":   100_000},
    {"name": "BikeWale",           "handle": "@BikeWaleOfficial",  "channel_url": "https://www.youtube.com/channel/UCYq67N0oJticIVD36iaXXgQ", "subs_estimate":   100_000},
    {"name": "ZigWheels",          "handle": "@ZigWheels",         "channel_url": "https://www.youtube.com/channel/UCjmjWp38PCg15Z5ZS-tmpfw", "subs_estimate":   100_000},
    {"name": "EVO India",          "handle": "@evoIndia",          "channel_url": "https://www.youtube.com/channel/UCAflTQOHfpuX3tEvN5mkLTg", "subs_estimate":    50_000},
]

# Cheap probe: how many videos to list when we have a cursor (i.e. we've
# refreshed this channel before). 10 is enough for daily-or-faster refresh
# cadence — most Indian moto channels post < 1 video/day.
PROBE_LIMIT = 10
# Catchup cap when probe didn't find the cursor (channel posted > PROBE_LIMIT
# since last refresh) or this is the first refresh ever for this channel.
CATCHUP_LIMIT = 50
# Backwards-compat alias (still referenced by main.py call sites).
DEFAULT_VIDEO_LIMIT = PROBE_LIMIT

# Cap shadow-row review_text at 4000 chars — videos are denser than text
# reviews so we keep more, but the embedding model is still 512-token-bound.
TRANSCRIPT_REVIEW_CAP = 4000


# ---------------------------------------------------------------------------
# Channel video listing via yt-dlp (no API key)
# ---------------------------------------------------------------------------

def list_channel_videos(channel_url: str, limit: int = DEFAULT_VIDEO_LIMIT) -> list[dict]:
    """Return [{video_id, title, description, duration_s, upload_date, url}]
    for the most recent `limit` uploads on `channel_url`. Uses yt-dlp's flat
    extraction so we get IDs+titles fast without per-video page loads.

    The /videos suffix on the channel URL is appended automatically when
    needed — yt-dlp accepts both forms but the /videos tab is what we want."""
    if not YT_DLP_AVAILABLE:
        raise RuntimeError("yt-dlp not installed. Run: pip install yt-dlp")

    url = channel_url if channel_url.rstrip("/").endswith("/videos") else channel_url.rstrip("/") + "/videos"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        print(f"[youtube] {channel_url}: list failed: {e}")
        return []

    entries = info.get("entries") or []
    out: list[dict] = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id")
        if not vid:
            continue
        out.append({
            "video_id": vid,
            "title": e.get("title") or "",
            "description": e.get("description") or "",
            "duration_s": e.get("duration"),
            # extract_flat doesn't always populate upload_date; fall back to
            # the channel index order (newest-first) implicit in `entries`.
            "upload_date": e.get("upload_date"),
            "url": e.get("url") or f"https://www.youtube.com/watch?v={vid}",
        })
    return out


# ---------------------------------------------------------------------------
# Bike matching — regex against the catalogue
# ---------------------------------------------------------------------------

# Known auto-caption misspellings to fold into the keyword regex. YouTube's
# auto-captions occasionally render brand names phonetically — these recover
# matches we'd otherwise miss.
CAPTION_ALIASES: dict[str, list[str]] = {
    "Pulsar":   ["pulser", "pulsor"],
    "Bajaj":    ["bhajaj", "bajaaj"],
    "Hayabusa": ["hyabusa", "habusa"],
}


def _make_keyword_regex(keywords: list[str]) -> re.Pattern:
    """Build a single case-insensitive regex matching any of the keywords
    as whole words. Sorted longest-first so 'Royal Enfield Classic 350'
    wins over 'Classic'."""
    expanded = list(keywords)
    for k in keywords:
        expanded.extend(CAPTION_ALIASES.get(k, []))
    expanded.sort(key=len, reverse=True)
    pattern = r"\b(?:" + "|".join(re.escape(k) for k in expanded) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


def match_bikes_in_text(title: str, description: str) -> list[dict]:
    """Return [{brand_id, canonical, bike_id, matched_keyword}] for every
    catalogue bike whose keywords appear in title+description. Empty list
    means 'not a review of any tracked bike' — caller skips.

    Two-stage filter: (1) keyword match against the catalogue, (2) require
    the bike's brand display name (or its brand_id) to also appear in the
    text. Stage 2 prevents generic-keyword false positives like 'BSA
    Scrambler 650 launched' attaching to Triumph/Ducati Scrambler entries.
    """
    text = f"{title}\n{description or ''}"
    text_lc = text.lower()
    matched: dict[str, dict] = {}
    for brand_id, models in bike_catalogue.CATALOGUE.items():
        # Brand-presence pre-check. Match either the brand_id (e.g. 'royal-
        # enfield' written as 'royal enfield' or 'royalenfield') or the
        # display name. Skips this brand entirely if neither appears.
        display = bike_catalogue.BRANDS.get(brand_id, {}).get("display", brand_id)
        brand_aliases = {
            display.lower(),
            brand_id.replace("-", " "),
            brand_id.replace("-", ""),
            brand_id,
        }
        if not any(alias in text_lc for alias in brand_aliases):
            continue

        for entry in models:
            canonical = entry["canonical"]
            keywords = entry.get("keywords") or [canonical]
            pat = _make_keyword_regex(keywords)
            m = pat.search(text)
            if not m:
                continue
            bike_id = bike_catalogue.make_bike_id(brand_id, canonical)
            if bike_id in matched:
                continue
            matched[bike_id] = {
                "brand_id": brand_id,
                "canonical": canonical,
                "bike_id": bike_id,
                "matched_keyword": m.group(0),
            }
    return list(matched.values())


# ---------------------------------------------------------------------------
# Transcript fetch
# ---------------------------------------------------------------------------

def fetch_transcript(video_id: str) -> tuple[str, str] | None:
    """Pull English captions for `video_id`. Returns (text, language) or None
    on no-captions / disabled / unavailable. Hindi-primary channels naturally
    drop out here — their videos rarely have en captions."""
    if not YT_TRANSCRIPT_AVAILABLE:
        raise RuntimeError("youtube-transcript-api not installed.")
    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=["en"])
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return None
    except Exception as e:
        # Catch network errors, IP throttling, format changes — skip gracefully
        print(f"[youtube] transcript fetch failed for {video_id}: {e}")
        return None

    parts: list[str] = []
    lang = "en"
    try:
        # FetchedTranscript supports iteration over snippet objects
        for snippet in transcript:
            text = getattr(snippet, "text", None) or (snippet.get("text") if isinstance(snippet, dict) else None)
            if text:
                parts.append(text)
        lang = getattr(transcript, "language_code", None) or "en"
    except Exception as e:
        print(f"[youtube] transcript decode failed for {video_id}: {e}")
        return None

    full = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if not full:
        return None
    return full, lang


# ---------------------------------------------------------------------------
# Top-level scrape
# ---------------------------------------------------------------------------

def _walk_until_cursor(videos: list[dict], cursor_video_id: str | None) -> list[dict]:
    """Walk the channel listing newest-first; stop the first time we hit the
    cursor video_id. Returns the prefix of new videos. If cursor is None
    (first refresh for this channel) returns everything."""
    out: list[dict] = []
    for v in videos:
        if cursor_video_id and v["video_id"] == cursor_video_id:
            break
        out.append(v)
    return out


def scrape_channel(
    channel: dict,
    skip_seen_video: callable = None,
    get_cursor: callable = None,
    set_cursor: callable = None,
) -> list[dict]:
    """Return new candidate videos for this channel. Fast path: when a cursor
    exists and the channel hasn't posted since, this returns [] after a single
    cheap PROBE_LIMIT-sized listing call.

    Two-phase walk:
      1. Probe with PROBE_LIMIT (cheap) — if cursor is in the window, only
         the prefix above it is "new", we're done.
      2. If probe didn't find cursor (channel posted >PROBE_LIMIT new videos
         OR first refresh ever), do a CATCHUP_LIMIT-sized listing.

    `skip_seen_video(video_id) -> bool` is a fallback de-dup so we never
    re-fetch a transcript even if cursor logic glitches.
    `get_cursor(handle) -> last_video_id | None` and
    `set_cursor(handle, video_id)` plug into the youtube_channel_cursor
    table. Both optional — when omitted, scraper degrades to its old
    full-listing behavior, useful for ad-hoc backfills.
    """
    handle = channel["handle"]
    name = channel["name"]
    channel_url = channel["channel_url"]

    cursor = get_cursor(handle) if get_cursor else None

    # Phase 1: cheap probe. Most refreshes terminate here.
    videos = list_channel_videos(channel_url, limit=PROBE_LIMIT)
    new_videos = _walk_until_cursor(videos, cursor)

    if cursor is None and new_videos and len(new_videos) == len(videos):
        # First refresh ever — pull a deeper window so we backfill history,
        # not just the latest 10.
        videos = list_channel_videos(channel_url, limit=CATCHUP_LIMIT)
        new_videos = _walk_until_cursor(videos, cursor)
    elif cursor is not None and len(new_videos) == len(videos) and len(videos) >= PROBE_LIMIT:
        # Probe was full of "new" videos but didn't hit the cursor — channel
        # posted more than PROBE_LIMIT since last refresh. Catch up.
        print(f"[youtube] {name}: probe full, expanding to {CATCHUP_LIMIT}")
        videos = list_channel_videos(channel_url, limit=CATCHUP_LIMIT)
        new_videos = _walk_until_cursor(videos, cursor)

    if cursor and not new_videos:
        # Fastest path: cursor matched the very newest video.
        print(f"[youtube] {name}: up-to-date (cursor at {cursor[:11]}…)")
        return []

    print(f"[youtube] {name}: {len(new_videos)} new since last refresh "
          f"(window={len(videos)}, cursor={'set' if cursor else 'first run'})")

    out: list[dict] = []
    for v in new_videos:
        # Filter 1: bike-keyword + brand-confirmation match
        matches = match_bikes_in_text(v["title"], v.get("description") or "")
        if not matches:
            continue

        # Filter 2: belt-and-braces — skip videos already transcribed.
        if skip_seen_video and skip_seen_video(v["video_id"]):
            continue

        # Filter 3: English transcript required
        result = fetch_transcript(v["video_id"])
        if not result:
            continue
        transcript, language = result

        out.append({
            "video_id": v["video_id"],
            "channel_handle": handle,
            "channel_name": name,
            "video_url": v["url"],
            "title": v["title"],
            "description": (v.get("description") or "")[:1000],
            "duration_s": v.get("duration_s"),
            "published_at": v.get("upload_date"),
            "transcript": transcript,
            "language": language,
            "matched_bikes": matches,
        })

        # Polite delay between transcript fetches.
        time.sleep(1.0)

    # Advance cursor to the newest video we LISTED (not just the newest we
    # processed) — that way next refresh starts from the same position even
    # if some videos got filtered (no bike match / no transcript).
    if videos and set_cursor:
        set_cursor(handle, videos[0]["video_id"])

    print(f"[youtube] {name}: {len(out)} kept of {len(new_videos)} new")
    return out


def scrape_all_channels(
    skip_seen_video: callable = None,
    get_cursor: callable = None,
    set_cursor: callable = None,
) -> list[dict]:
    """Iterate the CHANNELS registry; return a flat list of candidate videos
    ready for upsert. Each channel wrapped in try/except — one bad channel
    won't abort the rest."""
    out: list[dict] = []
    for ch in CHANNELS:
        try:
            out.extend(scrape_channel(
                ch,
                skip_seen_video=skip_seen_video,
                get_cursor=get_cursor,
                set_cursor=set_cursor,
            ))
        except Exception as e:
            print(f"[youtube] {ch['handle']} channel scrape failed: {e}")
    return out
