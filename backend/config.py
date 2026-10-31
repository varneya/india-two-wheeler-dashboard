"""
Central runtime configuration.

Every environment-driven knob lives here so the .env load happens exactly
once, explicitly — not as an import side effect. (Previously themes_llm.py
called load_dotenv() at import time, and the CORS setup in main.py only saw
.env values because main.py happened to import themes_runner → themes_llm
first. One import reorder away from silently breaking CORS.)

Values come from backend/.env (if present) and process env vars; real env
vars win over the file. See .env.example for the full list.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Auth (opt-in) ------------------------------------------------
    # When set, mutating/expensive endpoints require a matching
    # X-Admin-Token header. When unset (the local-first default where
    # every visitor runs their own backend), the guard is a no-op and
    # the API behaves exactly as before.
    admin_token: str | None = None

    # --- LLM backends ---------------------------------------------------
    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-4-6"
    # Groq speaks the OpenAI chat-completions dialect. The default free
    # tier is enough for nightly re-theming of changed bikes.
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # Generic OpenAI-compatible endpoint (Together, DeepInfra, vLLM, ...)
    # for the "openai:<model>" theme backend.
    openai_compat_base_url: str | None = None
    openai_compat_api_key: str | None = None

    # --- Ollama / embeddings ------------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    embedding_backend: str = "ollama"  # "ollama" | "sentence_transformers"

    # --- CORS ------------------------------------------------------------
    # Comma-separated extra origins; the deploy script sets this to the
    # public Caddy domain so this file never needs editing per-host.
    extra_cors_origins: str = ""

    @property
    def cors_origins(self) -> list[str]:
        base = ["http://localhost:5173", "https://varneya.github.io"]
        extra = [
            o.strip() for o in self.extra_cors_origins.split(",") if o.strip()
        ]
        return base + extra


settings = Settings()
