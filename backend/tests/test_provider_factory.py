"""Tests for make_provider / list_available_providers."""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.pipeline.providers import (
    list_available_providers,
    make_provider,
)
from app.pipeline.providers.claude import ClaudeHaikuProvider
from app.pipeline.providers.gemini import GeminiProvider


def _settings(**overrides) -> Settings:
    """Build Settings without consulting the actual .env file."""
    return Settings(_env_file=None, **overrides)


def test_make_claude_with_key():
    s = _settings(anthropic_api_key="sk-ant-test", gemini_api_key=None)
    p = make_provider("claude-haiku-4-5", s)
    assert isinstance(p, ClaudeHaikuProvider)
    assert p.name == "claude-haiku-4-5"


def test_make_gemini_2_5_with_key():
    s = _settings(anthropic_api_key=None, gemini_api_key="test")
    p = make_provider("gemini-2-5-flash", s)
    assert isinstance(p, GeminiProvider)
    assert p.name == "gemini-2-5-flash"
    assert p.variant == "2-5"


def test_make_gemini_3_with_key():
    s = _settings(anthropic_api_key=None, gemini_api_key="test")
    p = make_provider("gemini-3-flash", s)
    assert isinstance(p, GeminiProvider)
    assert p.variant == "3"
    assert p.is_preview is True


def test_make_provider_rejects_missing_anthropic_key():
    s = _settings(anthropic_api_key=None, gemini_api_key="x")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        make_provider("claude-haiku-4-5", s)


def test_make_provider_rejects_missing_gemini_key():
    s = _settings(anthropic_api_key="x", gemini_api_key=None)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        make_provider("gemini-3-flash", s)


def test_make_provider_rejects_unknown_id():
    s = _settings(anthropic_api_key="x", gemini_api_key="y")
    with pytest.raises(ValueError, match="Unknown model"):
        make_provider("gpt-4o", s)


def test_list_available_providers_marks_disabled():
    s = _settings(anthropic_api_key="x", gemini_api_key=None)
    infos = {info.id: info for info in list_available_providers(s)}
    assert infos["claude-haiku-4-5"].enabled is True
    assert infos["gemini-2-5-flash"].enabled is False
    assert infos["gemini-3-flash"].enabled is False
    assert infos["gemini-3-flash"].is_preview is False


def test_list_available_providers_all_disabled_when_no_keys():
    s = _settings(anthropic_api_key=None, gemini_api_key=None)
    for info in list_available_providers(s):
        assert info.enabled is False
