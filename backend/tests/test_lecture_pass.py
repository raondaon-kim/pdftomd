"""Tests for the pass-1 retry/validation orchestrator."""
from __future__ import annotations

from typing import Any

import pytest

from app.models import LectureContext, SlideOutlineEntry
from app.pipeline.lecture_pass import (
    PAGE_TEXT_TRIM_CHARS,
    extract_lecture_context,
)
from app.pipeline.providers.base import (
    LLMAuthError,
    LLMRateLimitError,
    LLMSchemaValidationError,
    LLMTransientError,
)


def _good_ctx(total_pages: int = 5) -> LectureContext:
    return LectureContext(
        title="강의",
        topic_summary="요약",
        slide_outline=[
            SlideOutlineEntry(page=i, title=f"p.{i}", one_line="line")
            for i in range(1, total_pages + 1)
        ],
        key_terms=["A"],
        domain_hints="d",
    )


class _ScriptedProvider:
    """Mock provider whose ``call_lecture_context`` returns/raises from a script."""

    name = "test"
    display_name = "Test"
    is_preview = False

    def __init__(self, script: list[Any]):
        self.script = list(script)
        self.captured_texts: list[list[str]] = []
        self.captured_total: list[int] = []

    def call_lecture_context(self, *, page_texts, mosaic_image_bytes, total_pages):
        self.captured_texts.append(list(page_texts))
        self.captured_total.append(total_pages)
        if not self.script:
            raise AssertionError("script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def call_page_analysis(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("pass-2 should not be called from pass-1 tests")


def test_returns_context_on_first_success():
    p = _ScriptedProvider([_good_ctx()])
    ctx = extract_lecture_context(
        p, page_texts=["a", "b", "c", "d", "e"], mosaic_image_bytes=b"", total_pages=5
    )
    assert ctx.title == "강의"


def test_retries_after_transient_error(monkeypatch: pytest.MonkeyPatch):
    p = _ScriptedProvider([LLMTransientError("net blip"), _good_ctx()])
    sleeps: list[float] = []
    ctx = extract_lecture_context(
        p,
        page_texts=["x"] * 5,
        mosaic_image_bytes=b"",
        total_pages=5,
        sleep=sleeps.append,  # type: ignore[arg-type]
    )
    assert ctx.title == "강의"
    assert sleeps == [1.0]  # one backoff


def test_retries_on_rate_limit():
    p = _ScriptedProvider(
        [LLMRateLimitError("429"), LLMRateLimitError("429"), _good_ctx()]
    )
    sleeps: list[float] = []
    ctx = extract_lecture_context(
        p,
        page_texts=["x"] * 5,
        mosaic_image_bytes=b"",
        total_pages=5,
        sleep=sleeps.append,  # type: ignore[arg-type]
    )
    assert ctx.title == "강의"
    assert sleeps == [1.0, 2.0]  # exponential


def test_auth_error_is_not_retried():
    p = _ScriptedProvider([LLMAuthError("bad key")])
    sleeps: list[float] = []
    with pytest.raises(LLMAuthError):
        extract_lecture_context(
            p,
            page_texts=["x"] * 5,
            mosaic_image_bytes=b"",
            total_pages=5,
            sleep=sleeps.append,  # type: ignore[arg-type]
        )
    assert sleeps == []  # never slept


def test_outline_validation_failure_triggers_retry_then_succeeds():
    bad_ctx = LectureContext(
        title="x",
        topic_summary="x",
        slide_outline=[
            SlideOutlineEntry(page=99, title="off-by-one", one_line="oops"),
        ],
        key_terms=[],
        domain_hints="d",
    )
    # First attempt: outline validation fails (page 99 > total_pages=5).
    # Second attempt: returns valid outline.
    p = _ScriptedProvider([bad_ctx, _good_ctx()])
    ctx = extract_lecture_context(
        p,
        page_texts=["x"] * 5,
        mosaic_image_bytes=b"",
        total_pages=5,
        sleep=lambda _: None,
    )
    assert ctx.title == "강의"


def test_strict_failure_after_max_retries():
    p = _ScriptedProvider(
        [LLMTransientError("a"), LLMTransientError("b"), LLMTransientError("c")]
    )
    with pytest.raises(LLMTransientError):
        extract_lecture_context(
            p,
            page_texts=["x"] * 5,
            mosaic_image_bytes=b"",
            total_pages=5,
            max_retries=3,
            sleep=lambda _: None,
        )


def test_strict_failure_on_validation():
    bad_ctx = LectureContext(
        title="x",
        topic_summary="x",
        slide_outline=[SlideOutlineEntry(page=99, title="off", one_line="oops")],
        key_terms=[],
        domain_hints="d",
    )
    p = _ScriptedProvider([bad_ctx, bad_ctx, bad_ctx])
    with pytest.raises(LLMSchemaValidationError):
        extract_lecture_context(
            p,
            page_texts=["x"] * 5,
            mosaic_image_bytes=b"",
            total_pages=5,
            max_retries=3,
            sleep=lambda _: None,
        )


def test_page_texts_are_trimmed():
    long_text = "a" * (PAGE_TEXT_TRIM_CHARS + 500)
    p = _ScriptedProvider([_good_ctx()])
    extract_lecture_context(
        p,
        page_texts=[long_text, "short"],
        mosaic_image_bytes=b"",
        total_pages=5,
    )
    captured = p.captured_texts[0]
    assert len(captured[0]) <= PAGE_TEXT_TRIM_CHARS + 50  # trim + marker
    assert "(truncated)" in captured[0]
    assert captured[1] == "short"
