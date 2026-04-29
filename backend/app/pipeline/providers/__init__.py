"""LLM provider adapters.

Each adapter implements the ``LLMProvider`` Protocol from ``base.py`` so the
runner is provider-agnostic. Concrete adapters (Claude, Gemini) live in
sibling modules.
"""
from __future__ import annotations

from app.core.config import Settings
from app.pipeline.providers.base import (
    LLMAuthError,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMSchemaValidationError,
    LLMTransientError,
    ProviderInfo,
)
from app.pipeline.providers.registry import (
    ALL_MODEL_IDS,
    CLAUDE_HAIKU_4_5,
    GEMINI_2_5_FLASH,
    GEMINI_3_FLASH,
    get_metadata,
)


def _has_api_key(model_id: str, settings: Settings) -> bool:
    if model_id == CLAUDE_HAIKU_4_5:
        return bool(settings.anthropic_api_key)
    if model_id in (GEMINI_2_5_FLASH, GEMINI_3_FLASH):
        return bool(settings.gemini_api_key)
    return False


def make_provider(model_id: str, settings: Settings) -> LLMProvider:
    """Construct a provider instance for ``model_id``.

    Raises ``ValueError`` if the model id is unknown or its API key is not set.
    """
    if model_id == CLAUDE_HAIKU_4_5:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        # Local import keeps optional SDKs out of the import graph until needed.
        from app.pipeline.providers.claude import ClaudeHaikuProvider
        return ClaudeHaikuProvider(settings.anthropic_api_key)
    if model_id in (GEMINI_2_5_FLASH, GEMINI_3_FLASH):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not set")
        from app.pipeline.providers.gemini import GeminiProvider
        variant = "2-5" if model_id == GEMINI_2_5_FLASH else "3"
        return GeminiProvider(settings.gemini_api_key, variant=variant)
    raise ValueError(f"Unknown model id: {model_id!r}")


def list_available_providers(settings: Settings) -> list[ProviderInfo]:
    """All known models with ``enabled`` reflecting key availability."""
    return [
        get_metadata(mid, enabled=_has_api_key(mid, settings))
        for mid in ALL_MODEL_IDS
    ]


__all__ = [
    "ALL_MODEL_IDS",
    "CLAUDE_HAIKU_4_5",
    "GEMINI_2_5_FLASH",
    "GEMINI_3_FLASH",
    "LLMAuthError",
    "LLMError",
    "LLMProvider",
    "LLMRateLimitError",
    "LLMSchemaValidationError",
    "LLMTransientError",
    "ProviderInfo",
    "list_available_providers",
    "make_provider",
]
