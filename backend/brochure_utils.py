"""
Shared helpers for OEM brochure scrapers.

Each per-OEM scraper handles discovery (find PDF URLs from the OEM's site)
and supplies its own slug → variant_id mapping. This module provides the
generic plumbing: rate-limited download, sha256 hashing, dedup against
already-stored brochures.

Brochure PDFs live on disk at brochures_cache/<sha256>.pdf — the DB only
stores metadata + hash so the schema stays small and re-downloads on a
known hash short-circuit.
"""

from __future__ import annotations

import hashlib
import os
import random
import time
from pathlib import Path
from typing import Iterable

import requests

BACKEND_DIR = Path(__file__).resolve().parent
BROCHURE_CACHE_DIR = BACKEND_DIR / "brochures_cache"

# Conservative cap — Hero's largest brochures are ~5 MB; flag anything
# meaningfully larger so a misrouted HTML page (which would be tiny) or
# a runaway download is caught.
MAX_PDF_BYTES = 25 * 1024 * 1024


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
}


def ensure_cache_dir() -> Path:
    BROCHURE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return BROCHURE_CACHE_DIR


def download_pdf(url: str, timeout: int = 30) -> tuple[bytes, str | None] | None:
    """GET a PDF. Returns (bytes, content_type) or None on failure.
    Refuses to return non-PDF responses (HTML error pages, etc.) by
    sniffing the magic header and Content-Type."""
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, stream=True)
    except requests.RequestException as e:
        print(f"[brochure] {url}: fetch failed {e}")
        return None
    if r.status_code != 200:
        print(f"[brochure] {url}: HTTP {r.status_code}")
        return None

    content = r.content
    if len(content) > MAX_PDF_BYTES:
        print(f"[brochure] {url}: oversized ({len(content)}b)")
        return None

    # Refuse non-PDFs — Hero (and others) sometimes return a 200 HTML page
    # for missing brochures rather than a 404.
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    looks_pdf = content[:5] == b"%PDF-"
    if not looks_pdf:
        print(f"[brochure] {url}: not a PDF (content-type={ctype}, first bytes={content[:8]!r})")
        return None
    return content, ctype or "application/pdf"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def save_pdf_to_cache(content: bytes) -> tuple[str, Path]:
    """Write the bytes to brochures_cache/<sha256>.pdf if not already there.
    Returns (sha256, absolute_path). Idempotent — re-saving the same bytes
    is a no-op."""
    ensure_cache_dir()
    digest = sha256_bytes(content)
    out = BROCHURE_CACHE_DIR / f"{digest}.pdf"
    if not out.exists():
        out.write_bytes(content)
    return digest, out


def relative_cache_path(absolute: Path) -> str:
    """Path stored in the DB — relative to BACKEND_DIR so the value is
    portable across machines."""
    return str(absolute.relative_to(BACKEND_DIR))


def polite_sleep(min_s: float = 1.0, max_s: float = 2.0):
    time.sleep(random.uniform(min_s, max_s))


def fetch_html(url: str, timeout: int = 25) -> str | None:
    """GET an HTML page with the standard headers. Returns text or None."""
    try:
        r = requests.get(url, headers={
            **DEFAULT_HEADERS,
            "Accept": "text/html,application/xhtml+xml",
        }, timeout=timeout)
        r.raise_for_status()
        return r.text
    except requests.RequestException as e:
        print(f"[brochure] {url}: fetch_html failed {e}")
        return None
