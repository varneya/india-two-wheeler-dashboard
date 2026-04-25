"""
Option 3 — LLM-based theme extraction.
Supports two backends:
  - "claude"         : Anthropic Claude API (needs ANTHROPIC_API_KEY)
  - "ollama:<model>" : Local Ollama (needs Ollama running)
"""

import json
import os
import re

import requests as http_requests
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """You are a product review analyst. You extract recurring themes from
motorcycle owner reviews and return structured JSON only — no commentary, no markdown."""

EXTRACT_PROMPT = """Analyse these {n} owner reviews of the Yamaha XSR 155 motorcycle in India.
Identify the 6-8 most discussed themes. For each theme return:
- name: short descriptive label (e.g. "Engine Performance", "Ride Comfort")
- sentiment: "positive", "negative", or "mixed"
- mention_count: estimated number of reviews touching this theme
- example_quotes: 2-3 short verbatim excerpts (max 120 chars each) that illustrate this theme
- keywords: 4-6 keywords associated with this theme

Return ONLY a JSON array of theme objects. No text outside the JSON.

Reviews:
{reviews}"""


def _build_prompt(reviews: list[dict]) -> str:
    # Sample up to 60 reviews — enough signal, avoids token limits
    sample = reviews[:60]
    formatted = "\n---\n".join(
        f"[{i+1}] {r['review_text'][:400]}" for i, r in enumerate(sample)
    )
    return EXTRACT_PROMPT.format(n=len(sample), reviews=formatted)


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

def _analyze_claude(reviews: list[dict]) -> list[dict] | dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or api_key == "your_api_key_here":
        return {"error": "ANTHROPIC_API_KEY not set. Add it to backend/.env"}

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=[{"type": "text", "text": SYSTEM_PROMPT,
                      "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _build_prompt(reviews)}],
        )
        return _parse_response(response.content[0].text)
    except Exception as e:
        return {"error": f"Claude API error: {e}"}


# ---------------------------------------------------------------------------
# Ollama backend
# ---------------------------------------------------------------------------

def _analyze_ollama(reviews: list[dict], model: str) -> list[dict] | dict:
    prompt = _build_prompt(reviews)
    try:
        resp = http_requests.post(
            "http://localhost:11434/api/chat",
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
# Unified entry point
# ---------------------------------------------------------------------------

def analyze(reviews: list[dict], backend: str = "claude") -> list[dict] | dict:
    """
    backend: "claude" | "ollama:<model-name>"
    """
    if backend == "claude":
        return _analyze_claude(reviews)
    elif backend.startswith("ollama:"):
        model = backend.split(":", 1)[1]
        return _analyze_ollama(reviews, model)
    else:
        return {"error": f"Unknown backend: {backend}. Use 'claude' or 'ollama:<model>'"}
