"""LLM provider adapters.

Each adapter implements the ``LLMProvider`` Protocol from ``base.py`` so the
runner is provider-agnostic. Concrete adapters (Claude, Gemini) live in
sibling modules.
"""
from __future__ import annotations

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
    GPT_5_4_MINI,
    GPT_5_MINI,
    get_metadata,
)

_OPENAI_MODEL_IDS = {GPT_5_MINI, GPT_5_4_MINI}


def make_provider(model_id: str, api_key: str) -> LLMProvider:
    """Construct a provider instance for ``model_id`` using the given API key.

    Raises ``ValueError`` if the model id is unknown or the key is empty.
    """
    if not api_key:
        raise ValueError(f"api_key is required for model '{model_id}'")
    if model_id == CLAUDE_HAIKU_4_5:
        from app.pipeline.providers.claude import ClaudeHaikuProvider
        return ClaudeHaikuProvider(api_key)
    if model_id in (GEMINI_2_5_FLASH, GEMINI_3_FLASH):
        from app.pipeline.providers.gemini import GeminiProvider
        variant = "2-5" if model_id == GEMINI_2_5_FLASH else "3"
        return GeminiProvider(api_key, variant=variant)
    if model_id in _OPENAI_MODEL_IDS:
        from app.pipeline.providers.openai import OpenAIProvider
        return OpenAIProvider(api_key, model_id=model_id)
    raise ValueError(f"Unknown model id: {model_id!r}")


def list_available_providers() -> list[ProviderInfo]:
    """All known models. ``enabled`` is always True — caller supplies the key at request time."""
    return [get_metadata(mid, enabled=True) for mid in ALL_MODEL_IDS]


__all__ = [
    "ALL_MODEL_IDS",
    "CLAUDE_HAIKU_4_5",
    "GEMINI_2_5_FLASH",
    "GEMINI_3_FLASH",
    "GPT_5_4_MINI",
    "GPT_5_MINI",
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
