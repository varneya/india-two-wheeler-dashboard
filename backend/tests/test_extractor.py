"""Small, synthetic article fixtures keep parser tests offline and readable."""

import pytest

from extractor import extract_sales_for_bike, extract_xsr_sales, month_from_url


@pytest.fixture
def article_url():
    return "https://news.example/yamaha-sales-december-2025-breakup"


@pytest.fixture
def xsr():
    return {
        "id": "yamaha-xsr-155", "model": "XSR 155",
        "keywords": ["XSR 155", "XSR"], "launch_month": "2025-11",
    }


@pytest.mark.parametrize("slug, expected", [
    ("sales-january-2026-breakup", "2026-01"),
    ("sales-feb-2026", "2026-02"),
    ("MARCH-2026/sales", "2026-03"),
    ("sales-sept-2025-breakup", "2025-09"),
    ("sales-december-2025-breakup", "2025-12"),
    ("sales-2026-01", None),
    ("sales-march-26-breakup", None),
    ("sales-march-20260-breakup", None),
    ("sales-smarch-2026-breakup", None),
    ("sales-report", None),
])
def test_month_from_article_url(slug, expected):
    assert month_from_url(f"https://news.example/{slug}") == expected


@pytest.mark.parametrize("text, units, confidence", [
    ("Yamaha XSR 155 recorded 14,951 units in December.", 14951, "high"),
    ("Sales reached 14,951 units for the Yamaha XSR 155.", 14951, "high"),
    ("XSR 155: 6,948", 6948, "medium"),
    ("The xsr recorded 12,345 units this month.", 12345, "high"),
])
def test_extract_article_patterns(text, units, confidence, article_url, xsr):
    assert extract_sales_for_bike(text, article_url, xsr) == {
        "bike_id": xsr["id"], "month": "2025-12", "units_sold": units,
        "source_url": article_url, "confidence": confidence,
    }


@pytest.mark.parametrize("text", [
    "", "A different motorcycle recorded 14,951 units.",
    "XSR 155 was reviewed. Another bike sold 14,951 units.",
    "XSR 155 was reviewed\nAnother bike sold 14,951 units.",
])
def test_unrelated_or_empty_text_does_not_make_a_sale(text, article_url, xsr):
    assert extract_sales_for_bike(text, article_url, xsr) is None


@pytest.mark.parametrize("slug", ["sales-october-2025-report", "sales-undated-report"])
def test_missing_month_or_before_launch_is_rejected(slug, xsr):
    assert extract_sales_for_bike(
        "XSR 155 sold 14,951 units.", f"https://news.example/{slug}", xsr
    ) is None


def test_launch_month_itself_is_allowed(xsr):
    result = extract_sales_for_bike(
        "XSR 155 sold 16,359 units.", "https://news.example/nov-2025-sales", xsr
    )
    assert result["units_sold"] == 16359


@pytest.mark.parametrize("units, accepted", [(49999, False), (50000, True), (250000, True)])
def test_high_volume_model_sanity_floor(units, accepted, article_url):
    bike = {"id": "honda-activa", "model": "Activa", "keywords": ["Activa"]}
    result = extract_sales_for_bike(f"Activa sold {units:,} units.", article_url, bike)
    if accepted:
        assert result["units_sold"] == units
    else:
        assert result is None


@pytest.mark.parametrize("units", [0, 1_000_001])
def test_zero_and_impossible_unit_counts_are_rejected(units, article_url):
    bike = {"id": "test-bike", "keywords": ["Roadster"]}
    assert extract_sales_for_bike(f"Roadster sold {units:,} units.", article_url, bike) is None


@pytest.mark.parametrize("keywords", [[], None])
def test_missing_keywords_are_safe(keywords, article_url, xsr):
    xsr["keywords"] = keywords
    assert extract_sales_for_bike("XSR 155 sold 14,951 units.", article_url, xsr) is None


def test_keyword_regex_metacharacters_are_literal(article_url):
    bike = {"id": "test-plus", "keywords": ["Roadster+"]}
    assert extract_sales_for_bike("Roadster sold 1,234 units.", article_url, bike) is None
    assert extract_sales_for_bike("Roadster+ sold 1,234 units.", article_url, bike)["units_sold"] == 1234


def test_legacy_extractor_preserves_old_response_shape(article_url, xsr):
    text = "XSR 155 sold 14,951 units."
    expected = extract_sales_for_bike(text, article_url, xsr)
    expected.pop("bike_id")
    assert extract_xsr_sales(text, article_url) == expected
    assert extract_xsr_sales(text, "https://news.example/oct-2025-sales") is None
