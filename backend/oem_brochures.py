"""Configurable OEM brochure discovery, matching, and ingestion.

Source policies deliberately retain the original URL grammars and slug rules.
In particular, Hero does not retry a product slug after an unmatched PDF slug;
Bajaj and Royal Enfield do. Transport and cache handling stay in brochure_utils.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Literal
from urllib.parse import urljoin

import brochure_utils as bu
import database


@dataclass(frozen=True)
class OEMConfig:
    brand_id: str
    display_name: str
    log_prefix: str
    base_url: str
    listing_url: str
    product_path_re: re.Pattern[str]
    pdf_link_re: re.Pattern[str]
    product_slug: Callable[[str], str]
    pdf_slug: Callable[[str], str]
    dedupe_products_by: Literal["url", "slug"] = "url"
    strip_product_trailing_slash: bool = False
    excluded_slugs: frozenset[str] = frozenset()
    brochure_name_hint_re: re.Pattern[str] | None = None
    normalize_variant_underscores: bool = False
    fallback_to_product_slug: bool = True
    unmatched_label: str = "unmatched product slugs:"


def discover_product_pages(config: OEMConfig) -> list[str]:
    """Discover products in listing order using the OEM's URL/dedup policy."""
    html = bu.fetch_html(config.listing_url)
    if not html:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in config.product_path_re.finditer(html):
        url = urljoin(config.base_url, match.group(1))
        if config.strip_product_trailing_slash:
            url = url.rstrip("/")
        slug = config.product_slug(url)
        key = slug if config.dedupe_products_by == "slug" else url
        if slug in config.excluded_slugs or key in seen:
            continue
        seen.add(key)
        out.append(url)
    return out


def extract_brochure_urls(config: OEMConfig, product_html: str) -> list[str]:
    """Extract ordered, unique PDFs, applying any OEM filename filter."""
    seen: set[str] = set()
    out: list[str] = []
    for match in config.pdf_link_re.finditer(product_html):
        url = urljoin(config.base_url, match.group(1))
        if config.brochure_name_hint_re is not None:
            if not config.brochure_name_hint_re.search(url.rsplit("/", 1)[-1]):
                continue
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def match_variant_id(config: OEMConfig, slug: str, variants: list[dict]) -> str | None:
    """Prefer exact suffix matches, then the original ordered prefix match."""
    if not slug:
        return None
    norm = slug.replace("-", "").replace("_", "").lower()
    for variant in variants:
        if variant["variant_id"].endswith(f"-{slug}"):
            return variant["variant_id"]
    for variant in variants:
        normalized_id = (
            variant["variant_id"].replace(f"{config.brand_id}-", "", 1)
            .replace("-", "").lower()
        )
        if config.normalize_variant_underscores:
            normalized_id = normalized_id.replace("_", "")
        if (normalized_id == norm or normalized_id.startswith(norm)
                or norm.startswith(normalized_id)):
            return variant["variant_id"]
    return None


def scrape(config: OEMConfig) -> dict:
    """Run an OEM pass; preserve counters, cache/upsert order, and throttling."""
    variants = database.list_variants(brand_id=config.brand_id, on_sale_only=False)
    prefix = f"[{config.log_prefix}]"
    print(f"{prefix} {len(variants)} {config.display_name} variants in DB")
    products = discover_product_pages(config)
    print(f"{prefix} discovered {len(products)} product pages")

    matched = unmatched = downloaded = skipped = failed = 0
    unmatched_slugs: list[str] = []
    for url in products:
        product_html = bu.fetch_html(url)
        bu.polite_sleep()
        if not product_html:
            failed += 1
            continue
        pdfs = extract_brochure_urls(config, product_html)
        if not pdfs:
            continue
        product_slug = config.product_slug(url)
        for pdf_url in pdfs:
            pdf_slug = config.pdf_slug(pdf_url) or product_slug
            variant_id = match_variant_id(config, pdf_slug, variants)
            if not variant_id and config.fallback_to_product_slug:
                variant_id = match_variant_id(config, product_slug, variants)
            if not variant_id:
                unmatched += 1
                unmatched_slugs.append(f"{pdf_slug} (from {url})")
                continue

            result = bu.download_pdf(pdf_url)
            bu.polite_sleep()
            if not result:
                failed += 1
                continue
            content, ctype = result
            digest, local = bu.save_pdf_to_cache(content)
            existing = database.list_brochures(variant_id)
            is_new = not any(b["sha256"] == digest for b in existing)
            database.upsert_brochure(
                variant_id=variant_id,
                brochure_url=pdf_url,
                sha256=digest,
                local_path=bu.relative_cache_path(local),
                file_size_bytes=len(content),
                content_type=ctype,
            )
            matched += 1
            if is_new:
                downloaded += 1
                print(f"{prefix} {variant_id}: NEW {len(content)//1024}KB {pdf_url}")
            else:
                skipped += 1

    print(f"\n{prefix} matched={matched} new_downloaded={downloaded} "
          f"already_seen={skipped} unmatched={unmatched} failed={failed}")
    if unmatched_slugs:
        print(f"{prefix} {config.unmatched_label}")
        for slug in unmatched_slugs:
            print(f"  - {slug}")
    return {
        "matched": matched,
        "downloaded": downloaded,
        "already_seen": skipped,
        "unmatched": unmatched,
        "failed": failed,
    }


# Hero: keep source URL grammars and filename interpretation separate.
HERO_BASE = "https://www.heromotocorp.com"

HERO_LISTING = f"{HERO_BASE}/en-in/motorcycles.html"

HERO_PRODUCT_PATH_RE = re.compile(
    r'href="((?:https?://www\.heromotocorp\.com)?/en-in/(?:motorcycles|scooters)/[^"\s]+\.html)"',
    re.IGNORECASE,
)

HERO_PDF_LINK_RE = re.compile(
    r'(?:href|data-href)="(/content/dam/[^"\s]+?\.pdf)"',
    re.IGNORECASE,
)

HERO_NON_PRODUCT_TAILS = {"order-booking", "test-ride", "book-now", "buy-now"}


def _hero_slug_from_url(product_url: str) -> str:
    """Last path segment without .html, e.g.
    '.../motorcycles/splendor-plus-xtec.html' → 'splendor-plus-xtec'.
    Strips category subpaths like '/practical/' that Hero adds for some
    legacy models."""
    tail = product_url.rstrip("/").split("/")[-1]
    return tail.removesuffix(".html").lower()


def _hero_slug_from_pdf_url(pdf_url: str) -> str:
    """Hero's PDF path includes the variant in the segment after
    /content-fragments/<variant>/ — we use that as a backup when the
    product-page slug doesn't disambiguate (e.g. Splendor+ page links
    PDFs for three different variants)."""
    m = re.search(r"/content-fragments/([^/]+)/", pdf_url)
    if m:
        return m.group(1).lower()
    return ""


HERO_CONFIG = OEMConfig(
    brand_id="hero",
    display_name="Hero",
    log_prefix="hero",
    base_url=HERO_BASE,
    listing_url=HERO_LISTING,
    product_path_re=HERO_PRODUCT_PATH_RE,
    pdf_link_re=HERO_PDF_LINK_RE,
    product_slug=_hero_slug_from_url,
    pdf_slug=_hero_slug_from_pdf_url,
    # Category subpaths can point to the same model; keep the first URL.
    dedupe_products_by="slug",
    excluded_slugs=frozenset(HERO_NON_PRODUCT_TAILS),
    normalize_variant_underscores=True,
    fallback_to_product_slug=False,
    unmatched_label="unmatched product slugs (catalogue gaps):",
)


# Bajaj: keep source URL grammars and filename interpretation separate.
BAJAJ_BASE = "https://www.bajajauto.com"

BAJAJ_LISTING = f"{BAJAJ_BASE}/bikes"

BAJAJ_PRODUCT_PATH_RE = re.compile(
    r'href="((?:https?://www\.bajajauto\.com)?/bikes/[a-z0-9-]+/[a-z0-9-]+)"',
    re.IGNORECASE,
)

BAJAJ_PDF_LINK_RE = re.compile(
    r'href="((?:/-/media|/media|https?://[^"]+/-/media)/[^"\s]+?\.pdf)"',
    re.IGNORECASE,
)


def _bajaj_slug_from_url(product_url: str) -> str:
    """'.../bikes/pulsar/pulsar-n160' -> 'pulsar-n160'."""
    return product_url.rstrip("/").split("/")[-1].lower()


def _bajaj_slug_from_pdf_url(pdf_url: str) -> str:
    """Extract the variant slug from the brochure filename.
    '.../n160-broucher/pulsar-n160-digital-brochure.pdf' -> 'pulsar-n160'.
    Used as a more-specific signal than the product page slug when one
    page hosts multiple variant PDFs."""
    fname = pdf_url.rstrip("/").split("/")[-1].lower()
    # Retain the original suffix grammar (it does not strip '-broucher').
    fname = re.sub(r"[-_](digital[-_])?bro?chure?\.pdf$", "", fname, flags=re.I)
    fname = fname.removesuffix(".pdf")
    return fname


BAJAJ_CONFIG = OEMConfig(
    brand_id="bajaj",
    display_name="Bajaj",
    log_prefix="bajaj",
    base_url=BAJAJ_BASE,
    listing_url=BAJAJ_LISTING,
    product_path_re=BAJAJ_PRODUCT_PATH_RE,
    pdf_link_re=BAJAJ_PDF_LINK_RE,
    product_slug=_bajaj_slug_from_url,
    pdf_slug=_bajaj_slug_from_pdf_url,
    strip_product_trailing_slash=True,
)


# Royal Enfield: keep source URL grammars and filename interpretation separate.
RE_BASE = "https://www.royalenfield.com"

RE_LISTING = f"{RE_BASE}/in/en/motorcycles/"

RE_PRODUCT_PATH_RE = re.compile(
    r'href="(/in/en/motorcycles/([a-z0-9][a-z0-9-]+)/?)"',
    re.IGNORECASE,
)

RE_NON_PRODUCT_SLUGS = {"motorcycle-booking", "test-ride", "book-now", "compare"}

RE_PDF_LINK_RE = re.compile(
    r'href="(/content/dam/[^"\s]+?\.pdf)"',
    re.IGNORECASE,
)

RE_BROCHURE_NAME_HINT_RE = re.compile(
    r"(brochure|technical[-_ ]?specification|spec[-_ ]?sheet|datasheet)",
    re.IGNORECASE,
)


def _royalenfield_slug_from_url(product_url: str) -> str:
    """'.../motorcycles/classic-350/' -> 'classic-350'."""
    parts = [p for p in product_url.rstrip("/").split("/") if p]
    return parts[-1].lower() if parts else ""


def _royalenfield_slug_from_pdf_url(pdf_url: str) -> str:
    """'.../royal-enfield-classic-350-technical-specifications-india-eng.pdf'
    -> 'classic-350'. RE prefixes the brand and suffixes the locale; we
    strip both to reveal the model slug."""
    fname = pdf_url.rsplit("/", 1)[-1].lower()
    fname = fname.removesuffix(".pdf")
    # Strip the leading 'royal-enfield-' (or 'royalenfield-')
    fname = re.sub(r"^royal[-_]?enfield[-_]", "", fname)
    # Strip trailing locale / spec-sheet markers
    for tail in (
        "-technical-specifications-india-eng",
        "-technical-specifications",
        "-brochure-india-eng",
        "-brochure-india",
        "-brochure",
        "-spec-sheet",
        "-datasheet",
    ):
        if fname.endswith(tail):
            fname = fname[: -len(tail)]
            break
    return fname.strip("-")


RE_CONFIG = OEMConfig(
    brand_id="royalenfield",
    display_name="Royal Enfield",
    log_prefix="re",
    base_url=RE_BASE,
    listing_url=RE_LISTING,
    product_path_re=RE_PRODUCT_PATH_RE,
    pdf_link_re=RE_PDF_LINK_RE,
    product_slug=_royalenfield_slug_from_url,
    pdf_slug=_royalenfield_slug_from_pdf_url,
    dedupe_products_by="slug",
    excluded_slugs=frozenset(RE_NON_PRODUCT_SLUGS),
    brochure_name_hint_re=RE_BROCHURE_NAME_HINT_RE,
)
