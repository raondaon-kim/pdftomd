"""OpenAI GPT-5.4 mini adapter (Chat Completions + Strict JSON Schema)."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import openai
from pydantic import BaseModel, ValidationError

from app.models import LectureContext, PageAnalysis
from app.pipeline.prompts import (
    PASS1_SYSTEM_PROMPT,
    build_pass1_user_text,
    build_pass2_system_prompt,
    build_pass2_user_text,
)
from app.pipeline.providers.base import (
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMSchemaValidationError,
    LLMTransientError,
    patch_page_analysis_payload,
)
from app.pipeline.providers.registry import (
    GPT_5_4_MINI,
    GPT_5_MINI,
    VENDOR_MODEL_IDS,
)

log = logging.getLogger(__name__)

# GPT-5.4 mini advertises a 128K-token max output. Pages rarely emit anywhere
# near that, but leaving headroom prevents truncation on dense slides — and
# OpenAI bills only on emitted tokens, so the ceiling is free.
_MAX_OUTPUT_TOKENS = 128_000
_TEMPERATURE = 0.0


# ---------------------------------------------------------------------------
# Strict-mode JSON Schema preparation
# ---------------------------------------------------------------------------

# OpenAI Structured Outputs (Strict mode) requires:
#   1. ``additionalProperties: false`` on every object
#   2. every property listed in ``required`` (no truly optional keys)
#   3. nullable values expressed as ``"type": ["X", "null"]`` (not via anyOf)
#   4. no unsupported keywords: format, default, $schema, examples, etc.
#
# Pydantic ``model_json_schema()`` violates 1, 2, and 3 — we patch them here.

_STRIP_KEYS = {
    "$schema",
    "$id",
    "$comment",
    "examples",
    "example",
    "default",
    "format",
    "readOnly",
    "writeOnly",
    "deprecated",
    "definitions",
}


def _prepare_strict_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Pydantic BaseModel -> OpenAI Strict JSON Schema."""
    raw = model_cls.model_json_schema()
    resolved = _resolve_refs(raw)
    nullable_flat = _flatten_anyof_nullable(resolved)
    strict = _enforce_strict(nullable_flat)
    return strict


def _resolve_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline every $ref pointing into $defs so the schema is self-contained."""
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
    """``anyOf: [<X>, {"type": "null"}]`` -> ``"type": ["X", "null"]``.

    Strict mode wants nullable types declared as a list rather than via anyOf.
    """
    if isinstance(node, dict):
        any_of = node.get("anyOf")
        if isinstance(any_of, list) and len(any_of) == 2:
            null_idx = next(
                (i for i, opt in enumerate(any_of)
                 if isinstance(opt, dict) and opt.get("type") == "null"),
                None,
            )
            if null_idx is not None:
                real = any_of[1 - null_idx]
                if isinstance(real, dict) and isinstance(real.get("type"), str):
                    merged = dict(real)
                    merged["type"] = [real["type"], "null"]
                    for k, v in node.items():
                        if k != "anyOf":
                            merged.setdefault(k, v)
                    return _flatten_anyof_nullable(merged)
        return {k: _flatten_anyof_nullable(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_flatten_anyof_nullable(item) for item in node]
    return node


def _enforce_strict(node: Any) -> Any:
    """Recurse: strip unsupported keys and enforce object-level strict rules."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in _STRIP_KEYS:
                continue
            out[k] = _enforce_strict(v)
        if out.get("type") == "object" and isinstance(out.get("properties"), dict):
            # Strict requires additionalProperties=false and every property in required.
            out["additionalProperties"] = False
            out["required"] = list(out["properties"].keys())
        return out
    if isinstance(node, list):
        return [_enforce_strict(item) for item in node]
    return node


# Pre-compute schemas once.
LECTURE_CONTEXT_SCHEMA = _prepare_strict_schema(LectureContext)
PAGE_ANALYSIS_SCHEMA = _prepare_strict_schema(PageAnalysis)


# ---------------------------------------------------------------------------
# Provider implementation
# ---------------------------------------------------------------------------


_OPENAI_DISPLAY: dict[str, str] = {
    GPT_5_MINI: "GPT-5 mini",
    GPT_5_4_MINI: "GPT-5.4 mini",
}


class OpenAIProvider:
    """Adapter for GPT-5 / GPT-5.4 family via Chat Completions + Strict JSON Schema."""

    is_preview = False

    def __init__(self, api_key: str, model_id: str = GPT_5_4_MINI):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIProvider")
        if model_id not in _OPENAI_DISPLAY:
            raise ValueError(f"Unsupported OpenAI model id: {model_id!r}")
        self.client = openai.OpenAI(api_key=api_key)
        self.name = model_id
        self.display_name = _OPENAI_DISPLAY[model_id]
        self.model_id = VENDOR_MODEL_IDS[model_id]
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    # --- pass 1 -----------------------------------------------------------

    def call_lecture_context(
        self,
        page_texts: list[str],
        mosaic_image_bytes: bytes,
        total_pages: int,
    ) -> LectureContext:
        joined = "\n\n".join(
            f"=== Page {i + 1} ===\n{text}" for i, text in enumerate(page_texts)
        )
        user_text = build_pass1_user_text(joined, total_pages)
        messages = self._build_messages(
            system=PASS1_SYSTEM_PROMPT,
            user_text=user_text,
            image_bytes=mosaic_image_bytes,
        )
        raw = self._invoke(
            messages=messages,
            schema=LECTURE_CONTEXT_SCHEMA,
            schema_name="lecture_context",
        )
        try:
            return LectureContext(**raw)
        except ValidationError as e:
            raise LLMSchemaValidationError(f"LectureContext validation failed: {e}") from e

    # --- pass 2 -----------------------------------------------------------

    def call_page_analysis(
        self,
        page_image_bytes: bytes,
        page_text: str,
        page_num: int,
        total_pages: int,
        context: LectureContext,
    ) -> PageAnalysis:
        system_prompt = build_pass2_system_prompt(context)
        user_text = build_pass2_user_text(page_text, page_num, total_pages)
        messages = self._build_messages(
            system=system_prompt,
            user_text=user_text,
            image_bytes=page_image_bytes,
        )
        raw = self._invoke(
            messages=messages,
            schema=PAGE_ANALYSIS_SCHEMA,
            schema_name="page_analysis",
        )
        patch_page_analysis_payload(raw, page_num)
        try:
            return PageAnalysis(**raw)
        except ValidationError as e:
            raise LLMSchemaValidationError(f"PageAnalysis validation failed: {e}") from e

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _build_messages(
        *,
        system: str,
        user_text: str,
        image_bytes: bytes,
    ) -> list[dict[str, Any]]:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        return [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": user_text},
                ],
            },
        ]

    def _invoke(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        schema_name: str,
    ) -> dict[str, Any]:
        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                temperature=_TEMPERATURE,
                max_completion_tokens=_MAX_OUTPUT_TOKENS,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    },
                },
            )
        except openai.AuthenticationError as e:
            raise LLMAuthError(str(e)) from e
        except openai.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except (openai.APIConnectionError, openai.APITimeoutError) as e:
            raise LLMTransientError(str(e)) from e
        except openai.APIStatusError as e:
            if 500 <= e.status_code < 600:
                raise LLMTransientError(str(e)) from e
            raise LLMError(f"OpenAI API error {e.status_code}: {e}") from e
        except openai.OpenAIError as e:
            raise LLMError(str(e)) from e

        usage = getattr(response, "usage", None)
        if usage is not None:
            self.total_input_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.total_output_tokens += getattr(usage, "completion_tokens", 0) or 0

        choice = response.choices[0]
        finish = choice.finish_reason
        message = choice.message
        text = message.content or ""

        # Strict JSON Schema mode can still return a refusal.
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise LLMSchemaValidationError(
                f"OpenAI refused to answer: {refusal!r} (finish_reason={finish!r})"
            )

        if not text:
            raise LLMSchemaValidationError(
                f"OpenAI returned no text in response; finish_reason={finish!r}"
            )

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            hint = ""
            if finish == "length":
                hint = (
                    " (response was truncated by max_completion_tokens; "
                    "raise _MAX_OUTPUT_TOKENS or split the page)"
                )
            raise LLMSchemaValidationError(
                f"OpenAI response was not valid JSON{hint}: {e}\n"
                f"finish_reason={finish!r}\n--- raw (first 500 chars) ---\n{text[:500]}"
            ) from e
