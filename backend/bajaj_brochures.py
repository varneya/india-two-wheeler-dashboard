"""Bajaj brochure scraper compatibility API; policies live in oem_brochures."""

from __future__ import annotations

import oem_brochures as _engine

# Retain module attributes used by existing callers and transport/DB mocks.
from oem_brochures import bu, database

CONFIG = _engine.BAJAJ_CONFIG
BAJAJ_BASE = _engine.BAJAJ_BASE
BAJAJ_LISTING = _engine.BAJAJ_LISTING
PRODUCT_PATH_RE = _engine.BAJAJ_PRODUCT_PATH_RE
PDF_LINK_RE = _engine.BAJAJ_PDF_LINK_RE


def discover_product_pages() -> list[str]:
    return _engine.discover_product_pages(CONFIG)


def extract_brochure_urls(product_html: str) -> list[str]:
    return _engine.extract_brochure_urls(CONFIG, product_html)


def _slug_from_url(product_url: str) -> str:
    return CONFIG.product_slug(product_url)


def _slug_from_pdf_url(pdf_url: str) -> str:
    return CONFIG.pdf_slug(pdf_url)


def match_variant_id(bajaj_slug: str, all_bajaj_variants: list[dict]) -> str | None:
    return _engine.match_variant_id(CONFIG, bajaj_slug, all_bajaj_variants)


def scrape() -> dict:
    return _engine.scrape(CONFIG)


if __name__ == "__main__":
    scrape()
