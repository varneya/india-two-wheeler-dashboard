"""
Reddit r/IndianBikes scraper using the public `.json` endpoints.

For each bike we:
  1. Search r/IndianBikes for posts matching the bike's display name
     (`/r/IndianBikes/search.json?q=...&restrict_sr=1&sort=relevance`)
  2. For the top N posts, fetch the comment thread JSON
     (`/comments/{post_id}/.json`)
  3. Keep top-level comments above a length / score floor

These count as "reviews" because r/IndianBikes is where Indian motorcycle
owners post first-hand opinions; comments on relevant posts are typically
substantive ("I've ridden the R15 V4 for 8 months, the pillion seat is...").

No auth required for read access. We pace requests to ~1/s to stay polite.
"""

from __future__ import annotations

import random
import re
import time

import requests

HEADERS = {
    # Reddit asks for a non-default UA — they 429 generic clients aggressively.
    "User-Agent": "india-two-wheeler-dashboard/0.1 (+https://github.com/varneya/india-two-wheeler-dashboard)",
    "Accept": "application/json",
}

BASE_URL = "https://www.reddit.com"
SUBREDDIT = "IndianBikes"

# Tunables — keep in code rather than args to keep `scrape_reddit_for_bike`
# signature-compatible with the other scrapers.
MAX_POSTS_PER_BIKE = 6
MAX_COMMENTS_PER_POST = 8
MIN_COMMENT_CHARS = 80
MIN_COMMENT_SCORE = 1


def _normalise_query(display_name: str) -> str:
    # Strip punctuation, collapse whitespace.
    q = re.sub(r"[^A-Za-z0-9 ]+", " ", display_name)
    return re.sub(r"\s+", " ", q).strip()


def _search_posts(query: str) -> list[dict]:
    url = f"{BASE_URL}/r/{SUBREDDIT}/search.json"
    params = {
        "q": query,
        "restrict_sr": "1",
        "sort": "relevance",
        "limit": str(MAX_POSTS_PER_BIKE),
    }
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    except requests.RequestException as e:
        print(f"[reddit] search failed for {query!r}: {e}")
        return []
    if resp.status_code != 200:
        print(f"[reddit] search HTTP {resp.status_code} for {query!r}")
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    return [c.get("data", {}) for c in data.get("data", {}).get("children", [])]


def _fetch_comments(post_id: str) -> list[dict]:
    url = f"{BASE_URL}/comments/{post_id}/.json"
    try:
        resp = requests.get(url, headers=HEADERS, params={"limit": "25"}, timeout=15)
    except requests.RequestException as e:
        print(f"[reddit] comments {post_id} failed: {e}")
        return []
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    # data is a 2-element list: [post_listing, comments_listing]
    if not isinstance(data, list) or len(data) < 2:
        return []
    children = data[1].get("data", {}).get("children", [])
    return [c.get("data", {}) for c in children if c.get("kind") == "t1"]


def scrape_reddit_for_bike(bike: dict) -> list[dict]:
    bike_id = bike["id"]
    query = _normalise_query(bike.get("display_name") or bike_id.replace("-", " "))
    if not query:
        return []

    time.sleep(random.uniform(1.0, 2.0))
    posts = _search_posts(query)
    if not posts:
        print(f"[reddit] {bike_id}: no posts for query={query!r}")
        return []

    out: dict[str, dict] = {}
    for post in posts[:MAX_POSTS_PER_BIKE]:
        pid = post.get("id")
        if not pid:
            continue
        permalink = f"{BASE_URL}{post.get('permalink', f'/comments/{pid}/')}"
        # Polite delay between thread fetches
        time.sleep(random.uniform(0.6, 1.2))
        comments = _fetch_comments(pid)
        kept = 0
        for cm in comments:
            cid = cm.get("id")
            body = (cm.get("body") or "").strip()
            score = cm.get("score") or 0
            if not cid or len(body) < MIN_COMMENT_CHARS or score < MIN_COMMENT_SCORE:
                continue
            post_id = f"reddit:{pid}:{cid}"
            if post_id in out:
                continue
            out[post_id] = {
                "bike_id": bike_id,
                "source": "reddit",
                "post_id": post_id,
                "username": cm.get("author") or "redditor",
                "review_text": body[:2000],
                # Reddit has no 1–5 rating; leave null. Score could be a proxy
                # (high upvotes = community-validated) but maps poorly to stars.
                "overall_rating": None,
                "thread_url": permalink,
            }
            kept += 1
            if kept >= MAX_COMMENTS_PER_POST:
                break

    print(f"[reddit] {bike_id}: {len(out)} comments across {len(posts)} posts")
    return list(out.values())
