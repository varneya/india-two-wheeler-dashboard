"""Hero brochure scraper compatibility API; policies live in oem_brochures."""

from __future__ import annotations

import oem_brochures as _engine

# Retain module attributes used by existing callers and transport/DB mocks.
from oem_brochures import bu, database

CONFIG = _engine.HERO_CONFIG
HERO_BASE = _engine.HERO_BASE
HERO_LISTING = _engine.HERO_LISTING
PRODUCT_PATH_RE = _engine.HERO_PRODUCT_PATH_RE
PDF_LINK_RE = _engine.HERO_PDF_LINK_RE
_NON_PRODUCT_TAILS = _engine.HERO_NON_PRODUCT_TAILS


def discover_product_pages() -> list[str]:
    return _engine.discover_product_pages(CONFIG)


def extract_brochure_urls(product_html: str) -> list[str]:
    return _engine.extract_brochure_urls(CONFIG, product_html)


def _slug_from_url(product_url: str) -> str:
    return CONFIG.product_slug(product_url)


def _slug_from_pdf_url(pdf_url: str) -> str:
    return CONFIG.pdf_slug(pdf_url)


def match_variant_id(hero_slug: str, all_hero_variants: list[dict]) -> str | None:
    return _engine.match_variant_id(CONFIG, hero_slug, all_hero_variants)


def scrape() -> dict:
    return _engine.scrape(CONFIG)


if __name__ == "__main__":
    scrape()
