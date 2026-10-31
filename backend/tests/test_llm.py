"""LLM request contracts with synthetic keys and mocked provider responses."""

import json
from unittest.mock import Mock

import pytest
import requests

import themes_llm


@pytest.fixture(autouse=True)
def llm_settings(monkeypatch):
    for name, value in {
        "anthropic_api_key": None, "groq_api_key": None,
        "groq_base_url": "https://groq.example/openai/v1/",
        "openai_compat_base_url": None, "openai_compat_api_key": None,
        "ollama_base_url": "http://ollama.example:11434",
    }.items():
        monkeypatch.setattr(themes_llm.settings, name, value)
    return themes_llm.settings


@pytest.fixture
def reviews():
    return [{"review_text": "The engine is smooth and the seat is comfortable."}]


@pytest.fixture
def themes():
    return [{"name": "Comfort", "sentiment": "positive", "mention_count": 1,
             "example_quotes": ["the seat is comfortable"], "keywords": ["seat"]}]


@pytest.fixture
def provider_post(monkeypatch, themes):
    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": json.dumps({"themes": themes})}}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(themes_llm.http_requests, "post", post)
    return post


def test_groq_request_contains_selected_subject_and_model(
    llm_settings, monkeypatch, reviews, themes, provider_post
):
    monkeypatch.setattr(llm_settings, "groq_api_key", "fake-test-key")
    result = themes_llm.analyze(reviews, "groq:llama-test", subject="the Hero Splendor Plus")
    assert result == themes
    provider_post.assert_called_once()
    args, kwargs = provider_post.call_args
    assert args == ("https://groq.example/openai/v1/chat/completions",)
    assert kwargs["headers"] == {"Authorization": "Bearer fake-test-key"}
    assert kwargs["timeout"] == 120
    payload = kwargs["json"]
    assert payload["model"] == "llama-test"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["messages"][0] == {"role": "system", "content": themes_llm.SYSTEM_PROMPT}
    prompt = payload["messages"][1]["content"]
    assert "the Hero Splendor Plus" in prompt
    assert "Yamaha XSR" not in prompt
    assert reviews[0]["review_text"] in prompt
    provider_post.return_value.raise_for_status.assert_called_once_with()


@pytest.mark.parametrize("key", [None, ""])
def test_groq_missing_key_fails_before_http(key, llm_settings, monkeypatch, reviews, provider_post):
    monkeypatch.setattr(llm_settings, "groq_api_key", key)
    result = themes_llm.analyze(reviews, "groq:llama-test", subject="Test bike")
    assert "Groq" in result["error"]
    assert "API key not set" in result["error"]
    provider_post.assert_not_called()


@pytest.mark.parametrize("key", [None, ""])
def test_keyless_openai_endpoint_omits_authorization(
    key, llm_settings, monkeypatch, reviews, themes, provider_post
):
    monkeypatch.setattr(llm_settings, "openai_compat_base_url", "http://local-model.example/v1/")
    monkeypatch.setattr(llm_settings, "openai_compat_api_key", key)
    assert themes_llm.analyze(reviews, "openai:local-model:tag") == themes
    args, kwargs = provider_post.call_args
    assert args == ("http://local-model.example/v1/chat/completions",)
    assert "authorization" not in {name.lower() for name in kwargs["headers"]}
    assert kwargs["json"]["model"] == "local-model:tag"
    assert themes_llm.DEFAULT_SUBJECT in kwargs["json"]["messages"][1]["content"]


def test_openai_endpoint_includes_key_when_configured(llm_settings, monkeypatch, reviews, provider_post):
    monkeypatch.setattr(llm_settings, "openai_compat_base_url", "https://compat.example/v1")
    monkeypatch.setattr(llm_settings, "openai_compat_api_key", "fake-compat-key")
    themes_llm.analyze(reviews, "openai:model")
    assert provider_post.call_args.kwargs["headers"] == {"Authorization": "Bearer fake-compat-key"}


def test_openai_missing_base_url_fails_before_http(reviews, provider_post):
    assert "OPENAI_COMPAT_BASE_URL not set" in themes_llm.analyze(reviews, "openai:model")["error"]
    provider_post.assert_not_called()


@pytest.mark.parametrize("key", [None, "", "your_api_key_here"])
def test_claude_missing_or_placeholder_key_never_creates_client(key, reviews, monkeypatch, llm_settings):
    import anthropic

    monkeypatch.setattr(llm_settings, "anthropic_api_key", key)
    constructor = Mock(side_effect=AssertionError("No paid API client should be created"))
    monkeypatch.setattr(anthropic, "Anthropic", constructor)
    assert "ANTHROPIC_API_KEY not set" in themes_llm.analyze(reviews, "claude")["error"]
    constructor.assert_not_called()


@pytest.mark.parametrize("wrapper", ["array", "object", "json-fence", "plain-fence"])
def test_parse_json_response_variants(themes, wrapper):
    raw = json.dumps({"themes": themes} if wrapper == "object" else themes)
    if wrapper == "json-fence":
        raw = f"```json\n{raw}\n```"
    elif wrapper == "plain-fence":
        raw = f"```\n{raw}\n```"
    assert themes_llm._parse_response(f" \n{raw}\n ") == themes


@pytest.mark.parametrize("raw, message", [
    ("not json", "JSON parse error"), ("", "JSON parse error"),
    ('{"unfinished":', "JSON parse error"),
    ('{"message": "unexpected"}', "Unexpected JSON structure"),
    ("null", "Unexpected JSON structure"), ("42", "Unexpected JSON structure"),
])
def test_malformed_or_unexpected_json_returns_error(raw, message):
    assert message in themes_llm._parse_response(raw)["error"]


def test_prompt_caps_review_count_and_length():
    reviews = [{"review_text": "x" * 400 + "TRUNCATED-SUFFIX"} for _ in range(60)]
    reviews.append({"review_text": "EXCLUDED-REVIEW"})
    prompt = themes_llm._build_prompt(reviews, "Royal Enfield two-wheelers (multiple models)")
    assert "60 owner reviews" in prompt
    assert "Royal Enfield two-wheelers (multiple models)" in prompt
    assert "[60]" in prompt
    assert "[61]" not in prompt
    assert "TRUNCATED-SUFFIX" not in prompt
    assert "EXCLUDED-REVIEW" not in prompt


def test_http_error_is_reported_with_provider(llm_settings, monkeypatch, reviews, provider_post):
    monkeypatch.setattr(llm_settings, "groq_api_key", "fake-test-key")
    provider_post.return_value.raise_for_status.side_effect = requests.HTTPError("503 unavailable")
    result = themes_llm.analyze(reviews, "groq:model")
    assert "Groq error" in result["error"]
    assert "503 unavailable" in result["error"]
    provider_post.return_value.json.assert_not_called()


def test_invalid_provider_payload_returns_error(llm_settings, monkeypatch, reviews, provider_post):
    monkeypatch.setattr(llm_settings, "groq_api_key", "fake-test-key")
    provider_post.return_value.json.return_value = {"choices": []}
    assert "Groq error" in themes_llm.analyze(reviews, "groq:model")["error"]


def test_unknown_backend_fails_before_http(reviews, provider_post):
    assert "Unknown backend" in themes_llm.analyze(reviews, "unknown:model")["error"]
    provider_post.assert_not_called()
