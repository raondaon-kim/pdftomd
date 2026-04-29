"""Tests for the shared patch_page_analysis_payload helper."""
from __future__ import annotations

from app.pipeline.providers.base import patch_page_analysis_payload


def test_fills_missing_page_num():
    raw: dict = {"classification": "content", "title": "t", "markdown_body": "b", "reasoning": "r"}
    patch_page_analysis_payload(raw, 7)
    assert raw["page_num"] == 7


def test_corrects_wrong_page_num():
    raw: dict = {
        "page_num": 99,
        "classification": "content",
        "title": "t",
        "markdown_body": "b",
        "reasoning": "r",
    }
    patch_page_analysis_payload(raw, 7)
    assert raw["page_num"] == 7


def test_clamps_overshoot_bbox():
    raw: dict = {
        "page_num": 27,
        "classification": "content",
        "title": "t",
        "markdown_body": "b",
        "image_region": {"x_min": -10, "y_min": 0, "x_max": 1100, "y_max": 1500},
        "reasoning": "r",
    }
    patch_page_analysis_payload(raw, 27)
    region = raw["image_region"]
    assert region["x_min"] == 0
    assert region["x_max"] == 1000
    assert region["y_max"] == 1000


def test_strips_image_region_on_decorative_only():
    raw: dict = {
        "page_num": 19,
        "classification": "decorative_only",
        "title": "video",
        "markdown_body": "watch",
        "image_region": {"x_min": 100, "y_min": 100, "x_max": 800, "y_max": 800},
        "image_caption": "lonely caption",
        "reasoning": "r",
    }
    patch_page_analysis_payload(raw, 19)
    assert raw["image_region"] is None
    assert raw["image_caption"] is None


def test_strips_image_region_on_section_divider():
    raw: dict = {
        "page_num": 5,
        "classification": "section_divider",
        "title": "복습",
        "markdown_body": "",
        "image_region": {"x_min": 100, "y_min": 100, "x_max": 800, "y_max": 800},
        "reasoning": "r",
    }
    patch_page_analysis_payload(raw, 5)
    assert raw["image_region"] is None


def test_drops_orphan_caption_when_region_absent():
    raw: dict = {
        "page_num": 14,
        "classification": "content",
        "title": "t",
        "markdown_body": "b",
        "image_region": None,
        "image_caption": "lonely caption",
        "reasoning": "r",
    }
    patch_page_analysis_payload(raw, 14)
    assert raw["image_region"] is None
    assert raw["image_caption"] is None


def test_keeps_image_region_on_content():
    raw: dict = {
        "page_num": 7,
        "classification": "content",
        "title": "t",
        "markdown_body": "b",
        "image_region": {"x_min": 50, "y_min": 50, "x_max": 950, "y_max": 950},
        "image_caption": "kept",
        "reasoning": "r",
    }
    patch_page_analysis_payload(raw, 7)
    assert raw["image_region"] is not None
    assert raw["image_caption"] == "kept"
