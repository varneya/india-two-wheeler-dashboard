"""
Option 3 — LLM-based theme extraction.
Supported backends:
  - "claude"         : Anthropic Claude API (needs ANTHROPIC_API_KEY)
  - "ollama:<model>" : Local Ollama (needs Ollama running)
  - "groq:<model>"   : Groq's OpenAI-compatible API (needs GROQ_API_KEY);
                       cheap/free hosted inference, e.g. "groq:llama-3.1-8b-instant"
  - "openai:<model>" : Any other OpenAI-compatible endpoint (Together,
                       DeepInfra, vLLM, ...) via OPENAI_COMPAT_BASE_URL +
                       OPENAI_COMPAT_API_KEY
"""

import json
import re

import requests as http_requests

from config import settings

SYSTEM_PROMPT = """You are a product review analyst. You extract recurring themes from
motorcycle owner reviews and return structured JSON only — no commentary, no markdown."""

EXTRACT_PROMPT = """Analyse these {n} owner reviews of {subject} in India.
Identify the 6-8 most discussed themes. For each theme return:
- name: short descriptive label (e.g. "Engine Performance", "Ride Comfort")
- sentiment: "positive", "negative", or "mixed"
- mention_count: estimated number of reviews touching this theme
- example_quotes: 2-3 short verbatim excerpts (max 120 chars each) that illustrate this theme
- keywords: 4-6 keywords associated with this theme

Return ONLY a JSON array of theme objects. No text outside the JSON.

Reviews:
{reviews}"""

# Used when the caller can't name the bike (shouldn't happen via
# themes_runner, which always passes one).
DEFAULT_SUBJECT = "this two-wheeler"


def _build_prompt(reviews: list[dict], subject: str | None) -> str:
    # Sample up to 60 reviews — enough signal, avoids token limits
    sample = reviews[:60]
    formatted = "\n---\n".join(
        f"[{i+1}] {r['review_text'][:400]}" for i, r in enumerate(sample)
    )
    return EXTRACT_PROMPT.format(
        n=len(sample), subject=subject or DEFAULT_SUBJECT, reviews=formatted
    )


def _parse_response(raw: str) -> list[dict] | dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "themes" in data:
            return data["themes"]
        return {"error": f"Unexpected JSON structure: {str(data)[:200]}"}
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e} — raw: {raw[:300]}"}


# ---------------------------------------------------------------------------
# Claude API backend
# ---------------------------------------------------------------------------

def _analyze_claude(reviews: list[dict], subject: str | None) -> list[dict] | dict:
    api_key = settings.anthropic_api_key
    if not api_key or api_key == "your_api_key_here":
        return {"error": "ANTHROPIC_API_KEY not set. Add it to backend/.env"}

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=2048,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                      "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _build_prompt(reviews, subject)}],
        )
        return _parse_response(response.content[0].text)
    except Exception as e:
        return {"error": f"Claude API error: {e}"}


# ---------------------------------------------------------------------------
# Ollama backend
# ---------------------------------------------------------------------------

def _analyze_ollama(reviews: list[dict], model: str, subject: str | None) -> list[dict] | dict:
    prompt = _build_prompt(reviews, subject)
    try:
        resp = http_requests.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "format": "json",
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return _parse_response(content)
    except http_requests.exceptions.ConnectionError:
        return {"error": "Ollama is not running. Start it with: ollama serve"}
    except Exception as e:
        return {"error": f"Ollama error: {e}"}


# ---------------------------------------------------------------------------
# OpenAI-compatible backend (Groq, Together, DeepInfra, vLLM, ...)
# ---------------------------------------------------------------------------

def _analyze_openai_compatible(
    reviews: list[dict],
    subject: str | None,
    *,
    base_url: str,
    api_key: str | None,
    model: str,
    provider: str,
    require_key: bool = False,
) -> list[dict] | dict:
    # Hosted providers (Groq) always need a key; the generic openai:<model>
    # backend also targets keyless self-hosted servers (vLLM, llama.cpp),
    # where we simply omit the Authorization header.
    if require_key and not api_key:
        return {"error": f"{provider}: API key not set. Add it to backend/.env"}
    try:
        resp = http_requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_prompt(reviews, subject)},
                ],
                "temperature": 0.2,
                # JSON mode: the model may wrap the array as {"themes": [...]},
                # which _parse_response unwraps.
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_response(content)
    except Exception as e:
        return {"error": f"{provider} error: {e}"}


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def analyze(
    reviews: list[dict],
    backend: str = "claude",
    subject: str | None = None,
) -> list[dict] | dict:
    """
    backend: "claude" | "ollama:<model>" | "groq:<model>" | "openai:<model>"
    subject: what the reviews are about — e.g. "the Hero Splendor Plus" or
             "Royal Enfield two-wheelers (multiple models)". Threaded into
             the prompt so the LLM isn't told every corpus is one bike.
    """
    if backend == "claude":
        return _analyze_claude(reviews, subject)
    elif backend.startswith("ollama:"):
        model = backend.split(":", 1)[1]
        return _analyze_ollama(reviews, model, subject)
    elif backend.startswith("groq:"):
        return _analyze_openai_compatible(
            reviews, subject,
            base_url=settings.groq_base_url,
            api_key=settings.groq_api_key,
            model=backend.split(":", 1)[1],
            provider="Groq",
            require_key=True,
        )
    elif backend.startswith("openai:"):
        if not settings.openai_compat_base_url:
            return {"error": "OPENAI_COMPAT_BASE_URL not set. Add it to backend/.env"}
        return _analyze_openai_compatible(
            reviews, subject,
            base_url=settings.openai_compat_base_url,
            api_key=settings.openai_compat_api_key,
            model=backend.split(":", 1)[1],
            provider="OpenAI-compatible endpoint",
        )
    else:
        return {
            "error": f"Unknown backend: {backend}. Use 'claude', "
                     "'ollama:<model>', 'groq:<model>' or 'openai:<model>'"
        }
