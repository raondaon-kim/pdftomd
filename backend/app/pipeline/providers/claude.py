"""Claude Haiku 4.5 adapter (Anthropic Tool Use)."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import anthropic
from pydantic import ValidationError

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
from app.pipeline.providers.registry import CLAUDE_HAIKU_4_5, VENDOR_MODEL_IDS

log = logging.getLogger(__name__)

# Claude Haiku 4.5 advertises a 64K-token output cap. We bill on emitted
# tokens only, so leaving the ceiling at the vendor max costs nothing for
# typical pages and prevents truncation on dense slides.
_MAX_TOKENS = 64_000
_TEMPERATURE = 0.0


# ---------------------------------------------------------------------------
# Tool definitions (Anthropic Tool Use)
# ---------------------------------------------------------------------------

# Pre-computed JSON schemas. Tool input_schema must be plain dict (no $defs / $ref).


def _flatten_schema(model_cls: type) -> dict[str, Any]:
    """Pydantic .model_json_schema() returns $defs+$ref structure that
    Anthropic Tool Use does not consistently handle. We resolve refs inline
    so the resulting schema is self-contained.
    """
    schema = model_cls.model_json_schema()
    defs = schema.pop("$defs", {})

    def _resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref and ref.startswith("#/$defs/"):
                key = ref.removeprefix("#/$defs/")
                resolved = defs.get(key, {})
                # Merge sibling keys (e.g. description) with resolved ref.
                merged = dict(resolved)
                for k, v in node.items():
                    if k != "$ref":
                        merged[k] = v
                return _resolve(merged)
            return {k: _resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_resolve(item) for item in node]
        return node

    return _resolve(schema)


TOOL_LECTURE_CONTEXT = {
    "name": "report_lecture_context",
    "description": "Report the lecture-wide context extracted from all pages.",
    "input_schema": _flatten_schema(LectureContext),
}

TOOL_PAGE_ANALYSIS = {
    "name": "report_page_analysis",
    "description": (
        "Report the analysis result of a single PDF slide page. Use this tool "
        "to return the classification, title, self-contained markdown body, "
        "and optional reference image region."
    ),
    "input_schema": _flatten_schema(PageAnalysis),
}


# ---------------------------------------------------------------------------
# Provider implementation
# ---------------------------------------------------------------------------


class ClaudeHaikuProvider:
    """Adapter for Claude Haiku 4.5 via Anthropic SDK."""

    name = CLAUDE_HAIKU_4_5
    display_name = "Claude Haiku 4.5"
    is_preview = False

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for ClaudeHaikuProvider")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model_id = VENDOR_MODEL_IDS[CLAUDE_HAIKU_4_5]

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
        messages = [
            {
                "role": "user",
                "content": [
                    self._image_block(mosaic_image_bytes),
                    {"type": "text", "text": user_text},
                ],
            }
        ]
        raw = self._invoke_tool(
            system=PASS1_SYSTEM_PROMPT,
            messages=messages,
            tool=TOOL_LECTURE_CONTEXT,
        )
        try:
            ctx = LectureContext(**raw)
        except ValidationError as e:
            raise LLMSchemaValidationError(f"LectureContext validation failed: {e}") from e
        return ctx

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
        messages = [
            {
                "role": "user",
                "content": [
                    self._image_block(page_image_bytes),
                    {"type": "text", "text": user_text},
                ],
            }
        ]
        raw = self._invoke_tool(
            system=system_prompt,
            messages=messages,
            tool=TOOL_PAGE_ANALYSIS,
        )
        patch_page_analysis_payload(raw, page_num)
        try:
            return PageAnalysis(**raw)
        except ValidationError as e:
            raise LLMSchemaValidationError(f"PageAnalysis validation failed: {e}") from e

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _image_block(image_bytes: bytes) -> dict[str, Any]:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(image_bytes).decode("ascii"),
            },
        }

    def _invoke_tool(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tool: dict[str, Any],
    ) -> dict[str, Any]:
        """Call the API forcing a specific tool, return the parsed tool input."""
        try:
            response = self.client.messages.create(
                model=self.model_id,
                max_tokens=_MAX_TOKENS,
                temperature=_TEMPERATURE,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=messages,
            )
        except anthropic.AuthenticationError as e:
            raise LLMAuthError(str(e)) from e
        except anthropic.RateLimitError as e:
            raise LLMRateLimitError(str(e)) from e
        except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
            raise LLMTransientError(str(e)) from e
        except anthropic.APIStatusError as e:
            if 500 <= e.status_code < 600:
                raise LLMTransientError(str(e)) from e
            raise LLMError(f"Anthropic API error {e.status_code}: {e}") from e
        except anthropic.AnthropicError as e:
            raise LLMError(str(e)) from e

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool["name"]:
                # Anthropic SDK returns input as a dict already.
                if isinstance(block.input, dict):
                    return block.input
                # Defensive: if it ever serializes as JSON string.
                return json.loads(block.input)  # type: ignore[arg-type]
        raise LLMSchemaValidationError(
            f"No {tool['name']} tool_use block in response; got blocks: "
            f"{[getattr(b, 'type', '?') for b in response.content]}"
        )
