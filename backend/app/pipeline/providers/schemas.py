"""Pydantic -> Gemini-compatible OpenAPI Schema dict.

Gemini's ``response_schema`` accepts a subset of OpenAPI 3.0 Schema. Pydantic's
``model_json_schema()`` emits JSON Schema (slightly different superset). This
module bridges the two:

- Inline ``$ref`` references from ``$defs``
- Replace ``Optional[X]`` (which becomes ``anyOf: [X, {type: null}]``) with
  ``nullable: true`` on the underlying type
- Convert ``"type": "integer"`` etc. to upper-case enum strings expected by
  Gemini (``INTEGER``, ``STRING``, ...)
- Strip fields Gemini does not recognize (``additionalProperties``,
  ``$schema``, ``title`` on the root, etc.)
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# Map JSON Schema primitive type names to Gemini's enum strings.
_TYPE_UPPER = {
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
    "null": "NULL",
}

# Keys that Gemini's Schema does not understand and that we drop.
#
# NOTE: We intentionally do NOT strip "title" because in our Pydantic models
# ``title`` is a real field name (SlideOutlineEntry.title, PageAnalysis.title).
# Pydantic also injects ``title`` as a *schema annotation*, but Gemini ignores
# unknown annotation keys — keeping them is harmless. Stripping by key name is
# unsafe when the key collides with a model field.
_STRIP_KEYS = {
    "$schema",
    "$id",
    "$comment",
    "additionalProperties",
    "patternProperties",
    "discriminator",
    "examples",  # Gemini supports `example` (singular)
    "readOnly",
    "writeOnly",
    "deprecated",
    "definitions",
}


def _resolve_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline every ``$ref`` pointing into ``$defs`` so the schema is self-contained."""
    defs = schema.get("$defs", {})

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node and node["$ref"].startswith("#/$defs/"):
                key = node["$ref"].removeprefix("#/$defs/")
                target = defs.get(key, {})
                merged = dict(target)
                for k, v in node.items():
                    if k != "$ref":
                        merged[k] = v
                return _walk(merged)
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node

    resolved = _walk(schema)
    if isinstance(resolved, dict):
        resolved.pop("$defs", None)
    return resolved


def _flatten_anyof_nullable(node: Any) -> Any:
    """Pydantic emits ``Optional[X]`` as ``anyOf: [<X>, {"type": "null"}]``.

    Gemini understands ``nullable: true`` instead. Detect that exact pattern
    and rewrite. Other ``anyOf`` shapes (real unions) are left as-is — Gemini
    can handle some but generators of structured output should design schemas
    to avoid them.
    """
    if isinstance(node, dict):
        any_of = node.get("anyOf")
        if isinstance(any_of, list) and len(any_of) == 2:
            null_idx = next(
                (i for i, opt in enumerate(any_of) if isinstance(opt, dict) and opt.get("type") == "null"),
                None,
            )
            if null_idx is not None:
                # The "real" branch is the other option.
                real = any_of[1 - null_idx]
                if isinstance(real, dict):
                    merged = dict(real)
                    merged["nullable"] = True
                    # Preserve sibling keys (description, title) from the original node
                    for k, v in node.items():
                        if k != "anyOf":
                            # Don't overwrite a description that came from the union member.
                            merged.setdefault(k, v)
                    return _flatten_anyof_nullable(merged)
        return {k: _flatten_anyof_nullable(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_flatten_anyof_nullable(item) for item in node]
    return node


def _normalize_types_and_strip(node: Any) -> Any:
    """Recurse: upper-case ``type`` values + drop unsupported keys."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in _STRIP_KEYS:
                continue
            if k == "type" and isinstance(v, str):
                out[k] = _TYPE_UPPER.get(v.lower(), v.upper())
            else:
                out[k] = _normalize_types_and_strip(v)
        return out
    if isinstance(node, list):
        return [_normalize_types_and_strip(item) for item in node]
    return node


def pydantic_to_gemini_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Top-level entry: ``BaseModel`` -> Gemini-compatible schema dict.

    Output is JSON-serializable and may be passed as ``response_schema``.
    """
    raw = model_cls.model_json_schema()
    resolved = _resolve_refs(raw)
    nullable_flat = _flatten_anyof_nullable(resolved)
    normalized = _normalize_types_and_strip(nullable_flat)
    return normalized
