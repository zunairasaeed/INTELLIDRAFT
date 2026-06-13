"""Application configuration loaded from environment variables.

Uses ``pydantic-settings`` so values can come from ``.env`` files,
process env, or runtime overrides during tests.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "LaTeX Editor"
    app_version: str = "0.1.0"
    debug: bool = False

    # LLM provider (Groq). When ``groq_api_key`` is unset the service
    # falls back to ``StubLLMClient`` so the rest of the loop still
    # runs end-to-end against real files.
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_temperature: float = 0.2
    groq_max_tokens: int = 2048

    # Persistence. Supabase is the production target; if either
    # credential is missing we use the in-memory ``DbClient`` (good
    # enough for local dev and the run-the-endpoint flow).
    supabase_url: str | None = None
    supabase_anon_key: str | None = None

    # Workspaces are materialised on disk under this root so a fresh
    # session can be parsed/edited without an upload step.
    workspace_root: Path = Field(default=Path("./workspaces"))

    # CORS (comma-separated list, or "*" for any)
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # ACM reference assets (used by the workspace bootstrap)
    acm_reference_dir: Path = Field(default=Path("./reference/acm"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()
