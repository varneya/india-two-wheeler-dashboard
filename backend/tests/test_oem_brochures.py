"""Offline regression fixtures for OEM policies and the shared ingestion loop.

Run from the repository root with:
    python -m unittest discover -s backend/tests -p test_oem_brochures.py -v

HTTP, database access, sleeps, and cache writes are mocked. Low-level guards
also fail the test if a scraper accidentally reaches requests or SQLite.
"""

from __future__ import annotations

import hashlib
import inspect
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import call, patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import bajaj_brochures as bajaj
import hero_brochures as hero
import oem_brochures as engine
import royalenfield_brochures as royal
sys.path.pop(0)


OEM_MODULES = (hero, bajaj, royal)

# Include valid links, duplicates, utility pages, and deliberately unsupported
# shapes. These encode the original regex grammars, including quote/query rules.
LISTINGS = {
    hero: (
        '''
        <a href="/en-in/motorcycles/practical/splendor-plus.html">first</a>
        <a href="https://www.heromotocorp.com/en-in/motorcycles/splendor-plus.html">duplicate</a>
        <a href="/en-in/motorcycles/SPLENDOR-PLUS.html">case duplicate</a>
        <a href="/en-in/scooters/pleasure-plus.html">scooter</a>
        <a href="http://www.heromotocorp.com/en-in/motorcycles/xtreme-125r.html">absolute</a>
        <a href="/en-in/motorcycles/test-ride.html">utility</a>
        <a href="/en-in/motorcycles/order-booking.html">utility</a>
        <a href="/en-in/scooters/book-now.html">utility</a>
        <a href="/en-in/motorcycles/buy-now.html">utility</a>
        <a href="/en-in/motorcycles.html">listing</a>
        <a href="/en-in/motorcycles/ignored.html?x=1">query</a>
        <a href='/en-in/motorcycles/single-quotes.html'>single quotes</a>
        <a href="https://other.example/en-in/motorcycles/offsite.html">offsite</a>
        ''',
        [
            hero.HERO_BASE + "/en-in/motorcycles/practical/splendor-plus.html",
            hero.HERO_BASE + "/en-in/scooters/pleasure-plus.html",
            "http://www.heromotocorp.com/en-in/motorcycles/xtreme-125r.html",
        ],
    ),
    bajaj: (
        '''
        <a href="/bikes/pulsar/pulsar-n160">first</a>
        <a href="https://www.bajajauto.com/bikes/pulsar/pulsar-n160">duplicate</a>
        <a href="/bikes/other/pulsar-n160">same tail, different URL</a>
        <a href="http://www.bajajauto.com/bikes/pulsar/pulsar-n160">different scheme</a>
        <a href="/bikes/pulsar/PULSAR-N160">different case</a>
        <a href="/bikes/avenger/avenger-220">next</a>
        <a href="/bikes">listing</a><a href="/bikes/pulsar">category</a>
        <a href="/bikes/pulsar/trailing/">unsupported trailing slash</a>
        <a href="/bikes/pulsar/model/extra">too deep</a>
        <a href="/bikes/pulsar/query?x=1">query</a>
        <a href="/bikes/pulsar/with_underscore">underscore</a>
        <a href='https://www.bajajauto.com/bikes/pulsar/single'>single quotes</a>
        <a href="https://other.example/bikes/pulsar/offsite">offsite</a>
        ''',
        [
            bajaj.BAJAJ_BASE + "/bikes/pulsar/pulsar-n160",
            bajaj.BAJAJ_BASE + "/bikes/other/pulsar-n160",
            "http://www.bajajauto.com/bikes/pulsar/pulsar-n160",
            bajaj.BAJAJ_BASE + "/bikes/pulsar/PULSAR-N160",
            bajaj.BAJAJ_BASE + "/bikes/avenger/avenger-220",
        ],
    ),
    royal: (
        '''
        <a href="/in/en/motorcycles/classic-350/">first</a>
        <a href="/in/en/motorcycles/classic-350">duplicate</a>
        <a href="/in/en/motorcycles/CLASSIC-350/">case duplicate</a>
        <a href="/in/en/motorcycles/new-himalayan">no slash</a>
        <a href="/in/en/motorcycles/motorcycle-booking/">utility</a>
        <a href="/in/en/motorcycles/test-ride/">utility</a>
        <a href="/in/en/motorcycles/book-now/">utility</a>
        <a href="/in/en/motorcycles/compare/">utility</a>
        <a href="https://www.royalenfield.com/in/en/motorcycles/meteor-350/">absolute ignored</a>
        <a href="/in/en/motorcycles/">listing</a>
        <a href="/in/en/motorcycles/classic-350/specs/">nested</a>
        <a href="/in/en/motorcycles/meteor-350/?x=1">query</a>
        <a href='/in/en/motorcycles/hunter-350/'>single quotes</a>
        ''',
        [
            royal.RE_BASE + "/in/en/motorcycles/classic-350/",
            royal.RE_BASE + "/in/en/motorcycles/new-himalayan",
        ],
    ),
}


class OEMBrochureTests(unittest.TestCase):
    def setUp(self):
        def mocked(target, **kwargs):
            patcher = patch(target, **kwargs)
            value = patcher.start()
            self.addCleanup(patcher.stop)
            return value

        mocked("requests.sessions.Session.request", side_effect=AssertionError("live HTTP forbidden"))
        mocked("sqlite3.connect", side_effect=AssertionError("live DB forbidden"))
        self.fetch = mocked("brochure_utils.fetch_html", side_effect=AssertionError("missing HTML fixture"))
        self.download = mocked("brochure_utils.download_pdf", side_effect=AssertionError("missing PDF fixture"))
        self.sleep = mocked("brochure_utils.polite_sleep")
        self.save = mocked("brochure_utils.save_pdf_to_cache", side_effect=self.fake_cache)
        self.variants = mocked("database.list_variants", return_value=[])
        self.existing = mocked("database.list_brochures", return_value=[])
        self.upsert = mocked("database.upsert_brochure")

    @staticmethod
    def fake_cache(content):
        digest = hashlib.sha256(content).hexdigest()
        return digest, BACKEND / "brochures_cache" / f"{digest}.pdf"

    def run_scrape(self, module, pages, variants, downloads=None):
        self.fetch.side_effect = pages.__getitem__
        self.variants.return_value = [{"variant_id": vid} for vid in variants]
        if downloads is not None:
            self.download.side_effect = downloads.__getitem__
        output = io.StringIO()
        with redirect_stdout(output):
            summary = module.scrape()
        return summary, output.getvalue()

    def test_listing_discovery_preserves_oem_url_and_dedupe_policies(self):
        for module, (html, expected) in LISTINGS.items():
            with self.subTest(oem=module.CONFIG.brand_id):
                self.fetch.side_effect = None
                self.fetch.return_value = html
                self.assertEqual(module.discover_product_pages(), expected)
                self.fetch.assert_called_with(module.CONFIG.listing_url)
        self.sleep.assert_not_called()

    def test_empty_and_failed_listings(self):
        for module in OEM_MODULES:
            for html in (None, "", "<p>No products</p>"):
                with self.subTest(oem=module.CONFIG.brand_id, html=html):
                    self.fetch.side_effect = None
                    self.fetch.return_value = html
                    self.assertEqual(module.discover_product_pages(), [])

    def test_hero_pdf_paths_and_data_attributes(self):
        html = '''
        <a href="/content/dam/hero-commerce/content-fragments/splendor-plus/brochure.pdf">
        <a data-href="/content/dam/hero-commerce/content-fragments/splendor-plus-xtec/brochure.pdf">
        <a href="/content/dam/hero-commerce/content-fragments/splendor-plus/brochure.pdf">
        <a HREF="/content/dam/hero/OTHER.PDF">
        <a href="/content/dam/hero/magazine.pdf">
        <a href="https://www.heromotocorp.com/content/dam/absolute.pdf">
        <a href="/media/not-hero.pdf"><a href="/content/dam/query.pdf?download=1">
        <a href='/content/dam/single.pdf'>
        '''
        self.assertEqual(hero.extract_brochure_urls(html), [hero.HERO_BASE + path for path in (
            "/content/dam/hero-commerce/content-fragments/splendor-plus/brochure.pdf",
            "/content/dam/hero-commerce/content-fragments/splendor-plus-xtec/brochure.pdf",
            "/content/dam/hero/OTHER.PDF", "/content/dam/hero/magazine.pdf",
        )])

    def test_bajaj_sitecore_and_absolute_pdf_paths(self):
        html = '''
        <a href="/-/media/Assets/pulsar-n160-digital-brochure.pdf">
        <a href="https://www.bajajauto.com/-/media/Assets/pulsar-n160-digital-brochure.pdf">
        <a href="/media/Assets/freedom-brochure.pdf">
        <a href="https://cdn.example/-/media/Assets/avenger-brochure.pdf">
        <a data-href="/-/media/Assets/dominar-brochure.pdf">
        <a href="https://cdn.example/media/absolute-plain-media.pdf">
        <a href="/content/dam/not-sitecore.pdf"><a href="/-/media/query.pdf?x=1">
        <a href='/-/media/single.pdf'>
        '''
        self.assertEqual(bajaj.extract_brochure_urls(html), [
            bajaj.BAJAJ_BASE + "/-/media/Assets/pulsar-n160-digital-brochure.pdf",
            bajaj.BAJAJ_BASE + "/media/Assets/freedom-brochure.pdf",
            "https://cdn.example/-/media/Assets/avenger-brochure.pdf",
            bajaj.BAJAJ_BASE + "/-/media/Assets/dominar-brochure.pdf",
        ])

    def test_royal_filters_pdf_filename_not_directory(self):
        names = ["classic-350-technical-specifications-india-eng.pdf", "meteor-brochure.pdf",
                 "hunter-spec_sheet.pdf", "himalayan-datasheet.pdf", "SHOTGUN-BROCHURE.PDF",
                 "bullet-technicalspecification.pdf"]
        html = "".join(f'<a href="/content/dam/open-pdf/{name}">' for name in names)
        html += '''
        <a href="/content/dam/open-pdf/meteor-brochure.pdf">
        <a data-href="/content/dam/open-pdf/bullet-spec-sheet.pdf">
        <a href="/content/dam/brochure/magazine.pdf">
        <a href="/content/dam/open-pdf/regulatory.pdf">
        <a href="https://www.royalenfield.com/content/dam/absolute-brochure.pdf">
        <a href="/content/dam/query-brochure.pdf?x=1">
        '''
        expected = [royal.RE_BASE + "/content/dam/open-pdf/" + name for name in names]
        expected.append(royal.RE_BASE + "/content/dam/open-pdf/bullet-spec-sheet.pdf")
        self.assertEqual(royal.extract_brochure_urls(html), expected)

    def test_product_slug_rules(self):
        fixtures = (
            (hero, "/en-in/motorcycles/practical/Splendor-Plus.html/", "splendor-plus"),
            # The original strips lowercase .html before lowercasing the tail.
            (hero, "/en-in/motorcycles/XTREME.HTML", "xtreme.html"),
            (bajaj, "/bikes/pulsar/PULSAR-N160/", "pulsar-n160"),
            (royal, "/in/en/motorcycles/CLASSIC-350/", "classic-350"),
            (royal, "", ""),
        )
        for module, url, expected in fixtures:
            with self.subTest(oem=module.CONFIG.brand_id, url=url):
                self.assertEqual(module._slug_from_url(url), expected)

    def test_hero_pdf_slug_requires_content_fragment(self):
        self.assertEqual(hero._slug_from_pdf_url(
            "/content/dam/hero/content-fragments/Splendor-Plus-XTEC/brochure.pdf"), "splendor-plus-xtec")
        self.assertEqual(hero._slug_from_pdf_url("/content/dam/splendor-plus-brochure.pdf"), "")

    def test_bajaj_filename_suffix_rules(self):
        fixtures = {
            "pulsar-n160-digital-brochure.pdf": "pulsar-n160",
            "PULSAR_NS400Z_DIGITAL_BROCHURE.PDF": "pulsar_ns400z",
            "freedom-brochure.pdf": "freedom",
            "ct110-brochur.pdf": "ct110",
            # Preserve the actual regex: the site's misspelling is not stripped.
            "pulsar-n160-broucher.pdf": "pulsar-n160-broucher",
            "plain.pdf": "plain",
        }
        for filename, expected in fixtures.items():
            with self.subTest(filename=filename):
                self.assertEqual(bajaj._slug_from_pdf_url("/-/media/" + filename), expected)

    def test_royal_brand_prefixes_and_locale_suffixes(self):
        for prefix in ("royal-enfield-", "royalenfield-", "royal_enfield_", ""):
            for tail in ("-technical-specifications-india-eng", "-technical-specifications",
                         "-brochure-india-eng", "-brochure-india", "-brochure", "-spec-sheet", "-datasheet"):
                with self.subTest(prefix=prefix, tail=tail):
                    self.assertEqual(royal._slug_from_pdf_url(
                        "/content/dam/" + prefix + "CLASSIC-350" + tail + ".PDF"), "classic-350")
        self.assertEqual(royal._slug_from_pdf_url("/content/dam/meteor-350-spec_sheet.pdf"), "meteor-350-spec_sheet")

    def test_matching_prefers_exact_then_first_fuzzy_prefix(self):
        for module in OEM_MODULES:
            brand = module.CONFIG.brand_id
            variants = [{"variant_id": brand + "-model-125-special"}, {"variant_id": brand + "-model-125"}]
            with self.subTest(oem=brand):
                self.assertEqual(module.match_variant_id("model-125", variants), brand + "-model-125")
                self.assertEqual(module.match_variant_id("MODEL_125", variants), brand + "-model-125-special")
                self.assertEqual(module.match_variant_id("model-125-extra", variants), brand + "-model-125")
                self.assertIsNone(module.match_variant_id("", variants))
                self.assertIsNone(module.match_variant_id("unknown", variants))
                self.assertIsNone(module.match_variant_id("model", []))

    def test_only_hero_removes_underscores_from_variant_ids(self):
        for module in OEM_MODULES:
            brand = module.CONFIG.brand_id
            vid = brand + "-model_125"
            with self.subTest(oem=brand):
                self.assertEqual(module.match_variant_id("model125", [{"variant_id": vid}]),
                                 vid if module is hero else None)

    def test_royal_does_not_invent_aliases_for_new_himalayan(self):
        self.assertIsNone(royal.match_variant_id("new-himalayan", [{"variant_id": "royalenfield-himalayan"}]))

    def test_public_function_signatures_and_engine_delegation(self):
        for module, slug_arg, variants_arg in (
            (hero, "hero_slug", "all_hero_variants"),
            (bajaj, "bajaj_slug", "all_bajaj_variants"),
            (royal, "re_slug", "all_re_variants"),
        ):
            for name, args in (("discover_product_pages", []), ("extract_brochure_urls", ["product_html"]),
                               ("match_variant_id", [slug_arg, variants_arg]), ("scrape", [])):
                with self.subTest(oem=module.CONFIG.brand_id, function=name):
                    self.assertEqual(list(inspect.signature(getattr(module, name)).parameters), args)
            with patch.object(engine, "scrape", return_value={"matched": 7}) as scrape:
                self.assertEqual(module.scrape(), {"matched": 7})
                scrape.assert_called_once_with(module.CONFIG)

    def test_empty_scrape_summary(self):
        for module in OEM_MODULES:
            with self.subTest(oem=module.CONFIG.brand_id):
                summary, _ = self.run_scrape(module, {module.CONFIG.listing_url: None}, [])
                self.assertEqual(summary, dict(matched=0, downloaded=0, already_seen=0, unmatched=0, failed=0))
                self.variants.assert_called_with(brand_id=module.CONFIG.brand_id, on_sale_only=False)
        self.download.assert_not_called()
        self.save.assert_not_called()
        self.upsert.assert_not_called()
        self.sleep.assert_not_called()

    def test_pdf_slug_preference_and_product_fallback_differ(self):
        fixtures = (
            (hero, "/en-in/motorcycles/splendor-plus.html", "splendor-plus", "splendor-plus-xtec",
             "/content/dam/content-fragments/splendor-plus-xtec/brochure.pdf",
             "/content/dam/content-fragments/unknown/brochure.pdf"),
            (bajaj, "/bikes/pulsar/pulsar-n160", "pulsar-n160", "pulsar-n250",
             "/-/media/pulsar-n250-digital-brochure.pdf", "/-/media/unknown-brochure.pdf"),
            (royal, "/in/en/motorcycles/classic-350/", "classic-350", "meteor-350",
             "/content/dam/royal-enfield-meteor-350-brochure.pdf", "/content/dam/unknown-brochure.pdf"),
        )
        for module, path, model, trim, trim_pdf, unknown_pdf in fixtures:
            with self.subTest(oem=module.CONFIG.brand_id):
                self.upsert.reset_mock()
                self.download.reset_mock()
                cfg = module.CONFIG
                product = cfg.base_url + path
                pdfs = [cfg.base_url + trim_pdf, cfg.base_url + unknown_pdf]
                pages = {cfg.listing_url: f'<a href="{path}">',
                         product: f'<a href="{trim_pdf}"><a href="{unknown_pdf}">'}
                summary, output = self.run_scrape(module, pages,
                    [cfg.brand_id + "-" + model, cfg.brand_id + "-" + trim],
                    {url: (b"%PDF-fixture", "application/pdf") for url in pdfs})
                expected_ids = [cfg.brand_id + "-" + trim]
                if module is not hero:
                    expected_ids.append(cfg.brand_id + "-" + model)
                self.assertEqual([c.kwargs["variant_id"] for c in self.upsert.call_args_list], expected_ids)
                self.assertEqual(self.download.call_args_list, [call(url) for url in pdfs[:len(expected_ids)]])
                self.assertEqual(summary, dict(matched=len(expected_ids), downloaded=len(expected_ids),
                                              already_seen=0, unmatched=int(module is hero), failed=0))
                if module is hero:
                    self.assertIn("[hero] unmatched product slugs (catalogue gaps):", output)
                    self.assertIn(f"unknown (from {product})", output)

    def test_hero_uses_page_slug_when_pdf_has_no_fragment(self):
        path = "/en-in/motorcycles/splendor-plus.html"
        pdf = "/content/dam/uninformative.pdf"
        summary, _ = self.run_scrape(hero, {
            hero.HERO_LISTING: f'<a href="{path}">',
            hero.HERO_BASE + path: f'<a href="{pdf}">',
        }, ["hero-splendor-plus"], {hero.HERO_BASE + pdf: (b"%PDF-fixture", None)})
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(self.upsert.call_args.kwargs["variant_id"], "hero-splendor-plus")
        self.assertIsNone(self.upsert.call_args.kwargs["content_type"])

    def test_full_ingestion_counters_metadata_dedup_and_throttling(self):
        """Exercise real discovery/matching with an in-memory existing-hash store."""
        for module in OEM_MODULES:
            with self.subTest(oem=module.CONFIG.brand_id):
                for mock in (self.fetch, self.download, self.sleep, self.save, self.upsert, self.existing):
                    mock.reset_mock()
                cfg = module.CONFIG
                if module is hero:
                    product_path = lambda slug: f"/en-in/motorcycles/{slug}.html"
                    pdf_path = lambda folder, slug: f"/content/dam/{folder}/content-fragments/{slug}/brochure.pdf"
                elif module is bajaj:
                    product_path = lambda slug: f"/bikes/pulsar/{slug}"
                    pdf_path = lambda folder, slug: f"/-/media/{folder}/{slug}-digital-brochure.pdf"
                else:
                    product_path = lambda slug: f"/in/en/motorcycles/{slug}/"
                    pdf_path = lambda folder, slug: f"/content/dam/{folder}/{slug}-technical-specifications-india-eng.pdf"
                products = [product_path(slug) for slug in ("model-125", "no-pdfs", "broken", "unknown")]
                paths = [pdf_path(folder, "model-125") for folder in ("new", "duplicate", "old", "failed")]
                unknown = pdf_path("unknown", "missing-model")
                pages = {
                    cfg.listing_url: "".join(f'<a href="{p}">' for p in products),
                    cfg.base_url + products[0]: "".join(f'<a href="{p}">' for p in paths + [paths[0]]),
                    cfg.base_url + products[1]: "<p>No PDF</p>",
                    cfg.base_url + products[2]: None,
                    cfg.base_url + products[3]: f'<a href="{unknown}">',
                }
                new, old = b"%PDF-new-fixture", b"%PDF-existing-fixture"
                downloads = {cfg.base_url + path: result for path, result in zip(paths, (
                    (new, "application/pdf"), (new, "application/pdf"), (old, "application/pdf"), None))}
                variant_id = cfg.brand_id + "-model-125"
                known = {variant_id: [{"sha256": hashlib.sha256(old).hexdigest()}]}
                self.existing.side_effect = lambda vid: list(known.get(vid, []))
                self.upsert.side_effect = lambda **row: known.setdefault(row["variant_id"], []).append(row)
                summary, output = self.run_scrape(module, pages, [variant_id], downloads)
                self.assertEqual(summary, dict(matched=3, downloaded=1, already_seen=2, unmatched=1, failed=2))
                self.variants.assert_called_with(brand_id=cfg.brand_id, on_sale_only=False)
                self.assertEqual(self.fetch.call_args_list, [call(cfg.listing_url)] +
                                 [call(cfg.base_url + p) for p in products])
                self.assertEqual(self.download.call_args_list, [call(cfg.base_url + p) for p in paths])
                self.assertEqual(self.sleep.call_count, 8)  # 4 products + 4 attempted downloads
                self.assertEqual(self.save.call_args_list, [call(new), call(new), call(old)])
                self.assertEqual(self.existing.call_args_list, [call(variant_id)] * 3)
                expected_upserts = []
                for path, content in zip(paths, (new, new, old)):
                    digest = hashlib.sha256(content).hexdigest()
                    expected_upserts.append(call(
                        variant_id=variant_id, brochure_url=cfg.base_url + path, sha256=digest,
                        local_path=f"brochures_cache/{digest}.pdf", file_size_bytes=len(content),
                        content_type="application/pdf"))
                self.assertEqual(self.upsert.call_args_list, expected_upserts)
                self.assertIn(f"[{cfg.log_prefix}] matched=3 new_downloaded=1 already_seen=2 unmatched=1 failed=2", output)
                self.assertIn(f"missing-model (from {cfg.base_url + products[3]})", output)


if __name__ == "__main__":
    unittest.main()
