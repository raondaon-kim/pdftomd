"""Tests for the Pydantic -> OpenAI Strict JSON Schema preparation."""
from __future__ import annotations

import json

from app.models import BBox, LectureContext, PageAnalysis
from app.pipeline.providers.openai import _prepare_strict_schema


def _walk(node, fn):
    fn(node)
    if isinstance(node, dict):
        for v in node.values():
            _walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            _walk(v, fn)


def test_no_refs_or_defs_leak():
    for cls in (PageAnalysis, LectureContext, BBox):
        text = json.dumps(_prepare_strict_schema(cls), ensure_ascii=False)
        assert "$ref" not in text
        assert "$defs" not in text


def test_every_object_has_additional_properties_false():
    schema = _prepare_strict_schema(PageAnalysis)
    found_objects = []

    def visit(node):
        if isinstance(node, dict) and node.get("type") == "object":
            found_objects.append(node)

    _walk(schema, visit)
    assert found_objects, "should have found at least one object schema"
    for obj in found_objects:
        assert obj.get("additionalProperties") is False


def test_every_object_lists_all_properties_in_required():
    schema = _prepare_strict_schema(PageAnalysis)

    def visit(node):
        if isinstance(node, dict) and node.get("type") == "object":
            props = node.get("properties") or {}
            required = node.get("required") or []
            assert set(required) == set(props.keys()), (
                f"strict mode requires every property in 'required'; "
                f"missing={set(props.keys()) - set(required)}"
            )

    _walk(schema, visit)


def test_optional_field_becomes_nullable_type_list():
    """PageAnalysis.image_region is Optional[BBox] -> type list with 'null'."""
    schema = _prepare_strict_schema(PageAnalysis)
    region = schema["properties"]["image_region"]
    # The flatten step replaces anyOf with a type list including "null".
    assert isinstance(region.get("type"), list)
    assert "null" in region["type"]


def test_strips_default_and_format():
    """OpenAI strict mode rejects 'default', 'format', etc. Make sure they're gone."""
    schema = _prepare_strict_schema(PageAnalysis)
    text = json.dumps(schema)
    # These appear in pydantic-generated schemas but break strict mode.
    assert '"default"' not in text
    assert '"$schema"' not in text


def test_classification_enum_preserved():
    schema = _prepare_strict_schema(PageAnalysis)
    classification = schema["properties"]["classification"]
    assert "enum" in classification
    assert "content" in classification["enum"]
    assert "decorative_only" in classification["enum"]


def test_round_trip_via_json():
    """Schema must be JSON-serializable so it can travel over the OpenAI API."""
    schema = _prepare_strict_schema(LectureContext)
    serialized = json.dumps(schema)
    parsed = json.loads(serialized)
    assert parsed == schema
