from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import BBox, LectureContext, PageAnalysis, SlideOutlineEntry


# ---------- BBox -----------------------------------------------------------


def test_bbox_rejects_inverted_coords():
    with pytest.raises(ValidationError):
        BBox(x_min=100, y_min=100, x_max=50, y_max=200)


def test_bbox_rejects_out_of_range():
    with pytest.raises(ValidationError):
        BBox(x_min=-1, y_min=0, x_max=100, y_max=100)
    with pytest.raises(ValidationError):
        BBox(x_min=0, y_min=0, x_max=1001, y_max=100)


# ---------- PageAnalysis ---------------------------------------------------


def test_page_analysis_content_with_image_ok():
    p = PageAnalysis(
        page_num=7,
        classification="content",
        title="t",
        markdown_body="b",
        image_region=BBox(x_min=0, y_min=0, x_max=1000, y_max=1000),
        image_caption="cap",
        reasoning="r",
    )
    assert p.image_region is not None
    assert p.image_caption == "cap"


def test_page_analysis_cover_with_image_rejected():
    with pytest.raises(ValidationError):
        PageAnalysis(
            page_num=1,
            classification="cover",
            title="",
            markdown_body="",
            image_region=BBox(x_min=0, y_min=0, x_max=1000, y_max=1000),
            reasoning="r",
        )


def test_page_analysis_caption_without_region_rejected():
    with pytest.raises(ValidationError):
        PageAnalysis(
            page_num=1,
            classification="content",
            title="t",
            markdown_body="b",
            image_caption="lonely",
            reasoning="r",
        )


# ---------- LectureContext -------------------------------------------------


def _ctx_with(outline: list[SlideOutlineEntry]) -> LectureContext:
    return LectureContext(
        title="t",
        topic_summary="s",
        slide_outline=outline,
        key_terms=[],
        domain_hints="d",
    )


def test_lecture_context_validates_pages_in_range():
    ctx = _ctx_with([SlideOutlineEntry(page=5, title="x", one_line="y")])
    ctx.validate_against_pdf(28)  # ok

    bad = _ctx_with([SlideOutlineEntry(page=99, title="x", one_line="y")])
    with pytest.raises(ValueError, match="outside range"):
        bad.validate_against_pdf(28)


def test_lecture_context_rejects_duplicate_pages():
    bad = _ctx_with(
        [
            SlideOutlineEntry(page=1, title="a", one_line="b"),
            SlideOutlineEntry(page=1, title="c", one_line="d"),
        ]
    )
    with pytest.raises(ValueError, match="duplicate"):
        bad.validate_against_pdf(28)


def test_lecture_context_rejects_empty_outline():
    with pytest.raises(ValidationError):
        _ctx_with([])
