from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models import LectureContext, PageAnalysis, SlideOutlineEntry
from app.pipeline.providers.base import LLMSchemaValidationError
from app.pipeline.providers.gemini import GeminiProvider


def test_init_requires_api_key():
    with pytest.raises(ValueError):
        GeminiProvider("", variant="2-5")


def test_init_rejects_unknown_variant():
    with pytest.raises(ValueError):
        GeminiProvider("test", variant="bogus")  # type: ignore[arg-type]


def test_variant_2_5_defaults():
    p = GeminiProvider("test", variant="2-5")
    assert p.name == "gemini-2-5-flash"
    assert p.temperature == 0.0
    assert p.thinking_level is None
    assert p.is_preview is False


def test_variant_3_defaults():
    p = GeminiProvider("test", variant="3")
    assert p.name == "gemini-3-flash"
    assert p.temperature == 1.0
    assert p.thinking_level == "minimal"
    assert p.is_preview is True


# --- mocking helpers -------------------------------------------------------


def _build_mock_response(payload: dict) -> SimpleNamespace:
    """Mimic genai response object's ``.text`` attribute."""
    return SimpleNamespace(text=json.dumps(payload), candidates=[])


def _stub_provider(payload: dict, variant: str = "2-5") -> GeminiProvider:
    p = GeminiProvider("test-key", variant=variant)
    p.client.models.generate_content = MagicMock(return_value=_build_mock_response(payload))
    return p


# --- happy paths -----------------------------------------------------------


def test_call_lecture_context_parses_payload():
    payload = {
        "title": "test",
        "topic_summary": "summary",
        "slide_outline": [{"page": 1, "title": "p1", "one_line": "intro"}],
        "key_terms": ["A"],
        "domain_hints": "AI",
    }
    p = _stub_provider(payload)
    ctx = p.call_lecture_context(
        page_texts=["x"],
        mosaic_image_bytes=b"\x89PNG",
        total_pages=1,
    )
    assert isinstance(ctx, LectureContext)
    assert ctx.title == "test"
    p.client.models.generate_content.assert_called_once()


def test_call_page_analysis_parses_payload():
    payload = {
        "page_num": 7,
        "classification": "content",
        "title": "t",
        "markdown_body": "b",
        "image_region": {"x_min": 0, "y_min": 0, "x_max": 1000, "y_max": 1000},
        "image_caption": "cap",
        "reasoning": "r",
    }
    p = _stub_provider(payload, variant="3")
    ctx = LectureContext(
        title="t",
        topic_summary="s",
        slide_outline=[SlideOutlineEntry(page=1, title="x", one_line="y")],
        key_terms=[],
        domain_hints="d",
    )
    page = p.call_page_analysis(
        page_image_bytes=b"\x89PNG",
        page_text="text",
        page_num=7,
        total_pages=10,
        context=ctx,
    )
    assert isinstance(page, PageAnalysis)
    assert page.page_num == 7
    assert page.image_region is not None


def test_call_page_analysis_clamps_overshoot_bbox():
    payload = {
        "page_num": 27,
        "classification": "content",
        "title": "t",
        "markdown_body": "b",
        "image_region": {"x_min": 50, "y_min": 100, "x_max": 1100, "y_max": 950},
        "image_caption": "cap",
        "reasoning": "r",
    }
    p = _stub_provider(payload)
    ctx = LectureContext(
        title="t",
        topic_summary="s",
        slide_outline=[SlideOutlineEntry(page=1, title="x", one_line="y")],
        key_terms=[],
        domain_hints="d",
    )
    page = p.call_page_analysis(
        page_image_bytes=b"x", page_text="t", page_num=27, total_pages=28, context=ctx
    )
    assert page.image_region is not None
    assert page.image_region.x_max == 1000  # clamped


def test_call_page_analysis_corrects_page_num():
    payload = {
        "page_num": 99,
        "classification": "content",
        "title": "t",
        "markdown_body": "b",
        "reasoning": "r",
    }
    p = _stub_provider(payload)
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


# --- error paths -----------------------------------------------------------


def test_invalid_json_raises_schema_validation():
    p = GeminiProvider("test-key", variant="2-5")
    p.client.models.generate_content = MagicMock(
        return_value=SimpleNamespace(text="not json {{{", candidates=[])
    )
    with pytest.raises(LLMSchemaValidationError):
        p.call_lecture_context(page_texts=[], mosaic_image_bytes=b"", total_pages=1)


def test_empty_response_raises_schema_validation():
    p = GeminiProvider("test-key", variant="2-5")
    p.client.models.generate_content = MagicMock(
        return_value=SimpleNamespace(text="", candidates=[])
    )
    with pytest.raises(LLMSchemaValidationError):
        p.call_lecture_context(page_texts=[], mosaic_image_bytes=b"", total_pages=1)


def test_invalid_payload_shape_raises_schema_validation():
    bad = {"title": "t"}  # missing required fields
    p = _stub_provider(bad)
    with pytest.raises(LLMSchemaValidationError):
        p.call_lecture_context(page_texts=[], mosaic_image_bytes=b"", total_pages=1)
