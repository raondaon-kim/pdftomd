"""Application settings loaded from environment variables.

Per docs/INFRA.md §4 — at least one LLM API key must be set; models without a
key are filtered out of the available list.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_root() -> Path:
    """Walk up from this file to the directory containing ``backend/``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "backend").is_dir():
            return parent
    return here.parent


def _find_env_file() -> str:
    """Walk up from this file looking for a .env (project root)."""
    candidate = _project_root() / ".env"
    if candidate.is_file():
        return str(candidate)
    return ".env"  # fall back to CWD


def _default_data_dir() -> Path:
    """Default to <project_root>/data so dev doesn't need /data on Windows."""
    return _project_root() / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM API keys — at least one must be set at startup
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None

    # Storage / runtime — accepts absolute or relative paths. Relative paths
    # (e.g. ``./data`` in .env) are resolved against the project root, not the
    # current working directory, so the location is stable regardless of where
    # the server is started from.
    data_dir: Path = _default_data_dir()

    @field_validator("data_dir", mode="after")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else (_project_root() / value).resolve()

    # Limits
    max_pdf_size_mb: int = 100
    max_pdf_pages: int = 100
    result_ttl_seconds: int = 3600
    render_dpi: int = 150

    # HTTP
    backend_port: int = 9007
    frontend_port: int = 9017
    cors_origins: str = "http://localhost:9017"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    def ensure_data_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    def validate_at_startup(self) -> None:
        """Raise if no LLM API key is configured (server cannot do useful work)."""
        if not (self.anthropic_api_key or self.gemini_api_key):
            raise RuntimeError(
                "No LLM API key configured. "
                "Set ANTHROPIC_API_KEY or GEMINI_API_KEY in environment / .env."
            )


_settings_override: Settings | None = None


@lru_cache(maxsize=1)
def _build_settings() -> Settings:
    return Settings()


def get_settings() -> Settings:
    if _settings_override is not None:
        return _settings_override
    return _build_settings()


def set_settings_for_tests(settings: Settings | None) -> None:
    """Test helper: install a hand-built Settings instance.

    Pass ``None`` to revert to the cached singleton built from env+.env.
    """
    global _settings_override
    _settings_override = settings


def reset_settings_cache() -> None:
    """Drop the cached default Settings (so the next call re-reads env+.env)."""
    _build_settings.cache_clear()  # type: ignore[attr-defined]
