from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pytest

from app.models import BBox, LectureContext, PageAnalysis, SlideOutlineEntry
from app.pipeline.providers.base import (
    LLMAuthError,
    LLMRateLimitError,
    LLMSchemaValidationError,
)
from app.pipeline.providers.claude import (
    TOOL_LECTURE_CONTEXT,
    TOOL_PAGE_ANALYSIS,
    ClaudeHaikuProvider,
)


def test_init_requires_api_key():
    with pytest.raises(ValueError):
        ClaudeHaikuProvider("")


def test_tool_schemas_have_no_refs():
    """Anthropic accepts $ref but we flatten for clarity. Re-check after edits."""
    s1 = json.dumps(TOOL_LECTURE_CONTEXT["input_schema"])
    s2 = json.dumps(TOOL_PAGE_ANALYSIS["input_schema"])
    assert "$ref" not in s1
    assert "$ref" not in s2
    # required keys must be present
    assert "title" in TOOL_LECTURE_CONTEXT["input_schema"]["required"]
    assert "page_num" in TOOL_PAGE_ANALYSIS["input_schema"]["required"]


# ---------- mocking helpers ------------------------------------------------


def _tool_use_block(name: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=payload)


def _build_provider_with_mock(tool_payload: dict, tool_name: str) -> ClaudeHaikuProvider:
    p = ClaudeHaikuProvider("sk-ant-test")
    fake_response = SimpleNamespace(content=[_tool_use_block(tool_name, tool_payload)])
    p.client.messages.create = MagicMock(return_value=fake_response)
    return p


# ---------- happy paths ----------------------------------------------------


def test_call_lecture_context_parses_tool_payload():
    payload = {
        "title": "test lecture",
        "topic_summary": "summary",
        "slide_outline": [{"page": 1, "title": "p1", "one_line": "intro"}],
        "key_terms": ["A", "B"],
        "domain_hints": "AI",
    }
    p = _build_provider_with_mock(payload, "report_lecture_context")
    ctx = p.call_lecture_context(
        page_texts=["page1 text"],
        mosaic_image_bytes=b"\x89PNG\r\n",
        total_pages=1,
    )
    assert isinstance(ctx, LectureContext)
    assert ctx.title == "test lecture"
    assert ctx.key_terms == ["A", "B"]
    p.client.messages.create.assert_called_once()
    kwargs = p.client.messages.create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "report_lecture_context"}


def test_call_page_analysis_parses_tool_payload():
    payload = {
        "page_num": 7,
        "classification": "content",
        "title": "title",
        "markdown_body": "body",
        "image_region": {"x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000},
        "image_caption": "cap",
        "reasoning": "r",
    }
    p = _build_provider_with_mock(payload, "report_page_analysis")
    ctx = LectureContext(
        title="t",
        topic_summary="s",
        slide_outline=[SlideOutlineEntry(page=1, title="x", one_line="y")],
        key_terms=[],
        domain_hints="d",
    )
    page = p.call_page_analysis(
        page_image_bytes=b"\x89PNG\r\n",
        page_text="text",
        page_num=7,
        total_pages=10,
        context=ctx,
    )
    assert isinstance(page, PageAnalysis)
    assert page.page_num == 7
    assert page.classification == "content"


def test_call_page_analysis_corrects_wrong_page_num():
    """If the model returns the wrong page_num we patch it to the truth."""
    payload = {
        "page_num": 99,  # wrong
        "classification": "content",
        "title": "t",
        "markdown_body": "b",
        "reasoning": "r",
    }
    p = _build_provider_with_mock(payload, "report_page_analysis")
    ctx = LectureContext(
        title="t",
        topic_summary="s",
        slide_outline=[SlideOutlineEntry(page=1, title="x", one_line="y")],
        key_terms=[],
        domain_hints="d",
    )
    page = p.call_page_analysis(
        page_image_bytes=b"x", page_text="t", page_num=7, total_pages=10, context=ctx
    )
    assert page.page_num == 7


# ---------- error paths ----------------------------------------------------


def _make_anthropic_error(cls, status_code: int, message: str = "err"):
    """Build an anthropic SDK exception via __new__ to skip the strict
    constructor (which wants a real httpx.Response). For test purposes we
    only need the class hierarchy to match what the provider catches.
    """
    err = cls.__new__(cls)
    Exception.__init__(err, message)
    err.status_code = status_code
    err.message = message
    err.body = None
    return err


def test_auth_error_raises_llm_auth_error():
    p = ClaudeHaikuProvider("sk-ant-test")
    err = _make_anthropic_error(anthropic.AuthenticationError, 401, "bad key")
    p.client.messages.create = MagicMock(side_effect=err)
    with pytest.raises(LLMAuthError):
        p.call_lecture_context(page_texts=[], mosaic_image_bytes=b"", total_pages=1)


def test_rate_limit_error_raises_llm_rate_limit():
    p = ClaudeHaikuProvider("sk-ant-test")
    err = _make_anthropic_error(anthropic.RateLimitError, 429, "rate")
    p.client.messages.create = MagicMock(side_effect=err)
    with pytest.raises(LLMRateLimitError):
        p.call_lecture_context(page_texts=[], mosaic_image_bytes=b"", total_pages=1)


def test_missing_tool_block_raises_schema_validation():
    p = ClaudeHaikuProvider("sk-ant-test")
    text_only = SimpleNamespace(content=[SimpleNamespace(type="text", text="oops")])
    p.client.messages.create = MagicMock(return_value=text_only)
    with pytest.raises(LLMSchemaValidationError):
        p.call_lecture_context(page_texts=[], mosaic_image_bytes=b"", total_pages=1)


def test_invalid_payload_raises_schema_validation():
    bad_payload = {
        "title": "t",
        "topic_summary": "s",
        "slide_outline": [{"page": 99, "title": "x", "one_line": "y"}],
        "key_terms": [],
        "domain_hints": "d",
    }
    # Pydantic itself accepts this (no total_pages context). The provider only
    # raises validation errors when Pydantic rejects, so use a malformed shape.
    really_bad = {"title": "t"}  # missing required fields
    p = _build_provider_with_mock(really_bad, "report_lecture_context")
    with pytest.raises(LLMSchemaValidationError):
        p.call_lecture_context(page_texts=[], mosaic_image_bytes=b"", total_pages=1)
