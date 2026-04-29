"""Tests for the Pydantic -> Gemini schema converter."""
from __future__ import annotations

import json

from pydantic import BaseModel

from app.models import BBox, LectureContext, PageAnalysis
from app.pipeline.providers.schemas import pydantic_to_gemini_schema


def _serialized(model_cls: type[BaseModel]) -> str:
    return json.dumps(pydantic_to_gemini_schema(model_cls), ensure_ascii=False)


def test_no_refs_or_defs_leak():
    for cls in (PageAnalysis, LectureContext, BBox):
        text = _serialized(cls)
        assert "$ref" not in text
        assert "$defs" not in text
        assert "definitions" not in text


def test_strips_additional_properties():
    text = _serialized(PageAnalysis)
    assert "additionalProperties" not in text


def test_optional_field_becomes_nullable():
    s = pydantic_to_gemini_schema(PageAnalysis)
    assert s["properties"]["image_region"].get("nullable") is True
    assert s["properties"]["image_caption"].get("nullable") is True
    # And there should be no remaining anyOf with null in those properties.
    region = s["properties"]["image_region"]
    assert "anyOf" not in region
    cap = s["properties"]["image_caption"]
    assert "anyOf" not in cap


def test_required_set_preserved():
    s = pydantic_to_gemini_schema(PageAnalysis)
    required = set(s["required"])
    assert {"page_num", "classification", "title", "markdown_body", "reasoning"} <= required
    # image_region / image_caption / image_filename should NOT be required.
    assert "image_region" not in required


def test_types_are_uppercased():
    s = pydantic_to_gemini_schema(BBox)
    # Every leaf type field should be in the upper-case enum form Gemini accepts.
    text = json.dumps(s)
    assert '"type": "object"' not in text
    assert '"type": "OBJECT"' in text
    assert '"type": "NUMBER"' in text


def test_classification_enum_preserved():
    s = pydantic_to_gemini_schema(PageAnalysis)
    classification = s["properties"]["classification"]
    enum = classification.get("enum")
    assert enum is not None
    assert set(enum) == {"content", "section_divider", "cover", "decorative_only"}


def test_lecture_context_outline_array_shape():
    s = pydantic_to_gemini_schema(LectureContext)
    outline = s["properties"]["slide_outline"]
    assert outline["type"] == "ARRAY"
    items = outline["items"]
    assert items["type"] == "OBJECT"
    # Inner SlideOutlineEntry fields must be inlined (no $ref).
    inner = items["properties"]
    assert {"page", "title", "one_line"} <= set(inner.keys())
    assert inner["page"]["type"] == "INTEGER"


def test_round_trip_via_json():
    """Output must be JSON-serializable (Gemini SDK requires plain dicts)."""
    for cls in (PageAnalysis, LectureContext, BBox):
        s = pydantic_to_gemini_schema(cls)
        json.dumps(s)  # would raise TypeError otherwise
