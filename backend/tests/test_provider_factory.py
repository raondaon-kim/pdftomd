"""Tests for make_provider / list_available_providers."""
from __future__ import annotations

import pytest

from app.pipeline.providers import (
    list_available_providers,
    make_provider,
)
from app.pipeline.providers.claude import ClaudeHaikuProvider
from app.pipeline.providers.gemini import GeminiProvider
from app.pipeline.providers.openai import OpenAIProvider


def test_make_claude_with_key():
    p = make_provider("claude-haiku-4-5", "sk-ant-test")
    assert isinstance(p, ClaudeHaikuProvider)
    assert p.name == "claude-haiku-4-5"


def test_make_gemini_2_5_with_key():
    p = make_provider("gemini-2-5-flash", "test")
    assert isinstance(p, GeminiProvider)
    assert p.name == "gemini-2-5-flash"
    assert p.variant == "2-5"


def test_make_gemini_3_with_key():
    p = make_provider("gemini-3-flash", "test")
    assert isinstance(p, GeminiProvider)
    assert p.variant == "3"
    assert p.is_preview is True


def test_make_gpt_5_4_mini_with_key():
    p = make_provider("gpt-5.4-mini", "sk-test")
    assert isinstance(p, OpenAIProvider)
    assert p.name == "gpt-5.4-mini"
    assert p.is_preview is False


def test_make_gpt_5_mini_with_key():
    p = make_provider("gpt-5-mini", "sk-test")
    assert isinstance(p, OpenAIProvider)
    assert p.name == "gpt-5-mini"
    assert p.is_preview is False


def test_make_provider_rejects_empty_key():
    with pytest.raises(ValueError, match="api_key is required"):
        make_provider("claude-haiku-4-5", "")


def test_make_provider_rejects_unknown_id():
    with pytest.raises(ValueError, match="Unknown model"):
        make_provider("gpt-4o", "sk-test")


def test_list_available_providers_all_enabled():
    infos = {info.id: info for info in list_available_providers()}
    assert infos["claude-haiku-4-5"].enabled is True
    assert infos["gemini-2-5-flash"].enabled is True
    assert infos["gemini-3-flash"].enabled is True
    assert infos["gpt-5.4-mini"].enabled is True
    assert infos["gpt-5-mini"].enabled is True


def test_list_available_providers_returns_all_models():
    infos = list_available_providers()
    assert len(infos) == 5
