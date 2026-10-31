"""Pin deterministic keyword behavior without model downloads or LLM calls."""

from copy import deepcopy

import pytest

import themes_keyword


@pytest.mark.parametrize("reviews", [[], [{}], [{"review_text": None}], [{"review_text": ""}]])
def test_empty_reviews_have_no_themes(reviews):
    assert themes_keyword.analyze(reviews) == []


def test_default_keywords_are_a_deep_copy():
    defaults = themes_keyword.get_default_keywords()
    expected = deepcopy(defaults)
    defaults["Engine & Performance"].append("test-only-token")
    defaults.pop("Braking")
    assert themes_keyword.get_default_keywords() == expected


def test_custom_keywords_replace_defaults_and_do_not_mutate_inputs():
    reviews = [{"review_text": "The engine is great and the panniers hold everything."}]
    keywords = {"Touring": ["PANNIERS"], "Disabled": [], "Blank": [""]}
    originals = deepcopy((reviews, keywords, themes_keyword.THEME_KEYWORDS))
    result = themes_keyword.analyze(reviews, keywords)
    assert [row["name"] for row in result] == ["Touring"]
    assert result[0]["keywords"] == ["PANNIERS"]
    assert (reviews, keywords, themes_keyword.THEME_KEYWORDS) == originals


def test_empty_override_uses_defaults():
    reviews = [{"review_text": "The engine is smooth and excellent on every ride."}]
    assert themes_keyword.analyze(reviews, {}) == themes_keyword.analyze(reviews)


def test_repeated_keywords_do_not_duplicate_a_sentence():
    sentence = "The engine has great power and the engine is smooth"
    result = themes_keyword.analyze(
        [{"review_text": sentence}], {"Engine": ["engine", "power", "smooth"]}
    )
    assert result == [{
        "name": "Engine", "sentiment": "positive", "mention_count": 1,
        "example_quotes": [sentence], "keywords": ["engine", "power", "smooth"],
    }]


def test_counts_are_matching_sentences_and_quotes_are_capped():
    sentences = [f"The engine is smooth on riding journey number {i}" for i in range(5)]
    keywords = ["engine", "power", "rpm", "torque", "speed", "cc", "throttle"]
    result = themes_keyword.analyze(
        [{"review_text": ". ".join(sentences)}], {"Engine": keywords}
    )[0]
    assert result["mention_count"] == 5
    assert result["example_quotes"] == sentences[:3]
    assert result["keywords"] == keywords[:6]


def test_first_matching_keyword_selects_quote_sentences():
    # One keyword per review per theme is the current matching contract.
    result = themes_keyword.analyze([{
        "review_text": "The engine feels calm during every journey. "
                       "The power delivery is great on every journey."
    }], {"Engine": ["engine", "power"]})
    assert result[0]["mention_count"] == 1
    assert result[0]["example_quotes"] == ["The engine feels calm during every journey"]


@pytest.mark.parametrize("text, sentiment", [
    ("The engine is excellent and smooth on every trip", "positive"),
    ("The engine is terrible and awful on every trip", "negative"),
    ("The engine is good but bad on every trip", "mixed"),
    ("The engine is present throughout every trip", "mixed"),
    ("The engine is good great bad on every trip", "mixed"),
])
def test_sentiment_thresholds(text, sentiment):
    result = themes_keyword.analyze([{"review_text": text}], {"Engine": ["engine"]})
    assert result[0]["sentiment"] == sentiment


def test_stems_match_and_short_quotes_are_ignored():
    assert themes_keyword.analyze(
        [{"review_text": "Vibration is noticeable throughout the daily journey"}],
        {"Build": ["vibrat"]},
    )[0]["mention_count"] == 1
    assert themes_keyword.analyze(
        [{"review_text": "Good engine!"}], {"Engine": ["engine"]}
    ) == []


def test_more_frequent_themes_sort_first():
    reviews = [
        {"review_text": "The brakes feel consistent throughout every journey"},
        {"review_text": "The engine feels consistent throughout every journey"},
        {"review_text": "The brakes feel consistent on the return journey too"},
    ]
    result = themes_keyword.analyze(reviews, {"Engine": ["engine"], "Brakes": ["brakes"]})
    assert [(row["name"], row["mention_count"]) for row in result] == [("Brakes", 2), ("Engine", 1)]
