"""Gemini 2.5 Flash and Gemini 3 Flash adapter.

Both variants share this adapter; differences (model id, temperature,
thinking_level, preview flag) are configured via the ``variant`` argument.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Literal

from google import genai
from google.api_core import exceptions as gax_exc
from google.genai import errors as genai_errors
from google.genai import types as genai_types
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
from app.pipeline.providers.registry import (
    GEMINI_2_5_FLASH,
    GEMINI_3_FLASH,
    VENDOR_MODEL_IDS,
)
from app.pipeline.providers.schemas import pydantic_to_gemini_schema

log = logging.getLogger(__name__)

# We let the model emit as much as the vendor permits per response. Both
# Gemini 2.5 Flash and Gemini 3 Flash advertise a 65,536-token output cap. We
# bill on emitted tokens only, so leaving the ceiling high costs nothing for
# typical pages (a few KB) and prevents MAX_TOKENS truncation on the rare
# dense slide (e.g. a slide deep in a Korean lecture full of diagrams).
_MAX_OUTPUT_TOKENS_BY_VARIANT: dict[str, int] = {
    "2-5": 65_536,
    "3": 65_536,
}

# Pre-built schemas (independent of variant).
LECTURE_CONTEXT_SCHEMA = pydantic_to_gemini_schema(LectureContext)
PAGE_ANALYSIS_SCHEMA = pydantic_to_gemini_schema(PageAnalysis)


GeminiVariant = Literal["2-5", "3"]


class GeminiProvider:
    """Adapter shared by Gemini 2.5 Flash and Gemini 3 Flash."""

    def __init__(self, api_key: str, variant: GeminiVariant):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiProvider")
        if variant not in ("2-5", "3"):
            raise ValueError(f"Unknown Gemini variant: {variant!r}")
        self.client = genai.Client(api_key=api_key)
        self.variant = variant

        if variant == "2-5":
            self.name = GEMINI_2_5_FLASH
            self.display_name = "Gemini 2.5 Flash"
            self.is_preview = False
            self.temperature = 0.0
            self.thinking_level: str | None = None
        else:  # "3"
            self.name = GEMINI_3_FLASH
            self.display_name = "Gemini 3 Flash"
            self.is_preview = True
            self.temperature = 1.0  # 3.x recommends not lowering this
            self.thinking_level = "minimal"

        self.model_id = VENDOR_MODEL_IDS[self.name]

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
        contents = self._build_contents(mosaic_image_bytes, user_text)
        raw = self._invoke(
            system=PASS1_SYSTEM_PROMPT,
            contents=contents,
            schema=LECTURE_CONTEXT_SCHEMA,
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
        contents = self._build_contents(page_image_bytes, user_text)
        raw = self._invoke(
            system=system_prompt,
            contents=contents,
            schema=PAGE_ANALYSIS_SCHEMA,
        )
        patch_page_analysis_payload(raw, page_num)
        try:
            return PageAnalysis(**raw)
        except ValidationError as e:
            raise LLMSchemaValidationError(f"PageAnalysis validation failed: {e}") from e

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _build_contents(image_bytes: bytes, user_text: str) -> list[Any]:
        """Single-turn user content: image part + text part."""
        return [
            genai_types.Content(
                role="user",
                parts=[
                    genai_types.Part(
                        inline_data=genai_types.Blob(
                            mime_type="image/png", data=image_bytes
                        )
                    ),
                    genai_types.Part(text=user_text),
                ],
            )
        ]

    def _build_config(self, system: str, schema: dict[str, Any]) -> genai_types.GenerateContentConfig:
        cfg_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": schema,
            "temperature": self.temperature,
            "max_output_tokens": _MAX_OUTPUT_TOKENS_BY_VARIANT[self.variant],
            "system_instruction": system,
        }
        if self.thinking_level:
            cfg_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                thinking_level=self.thinking_level,
            )
        return genai_types.GenerateContentConfig(**cfg_kwargs)

    def _invoke(
        self,
        *,
        system: str,
        contents: list[Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        config = self._build_config(system, schema)
        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                contents=contents,
                config=config,
            )
        except genai_errors.ClientError as e:
            # google-genai's own error class for 4xx — covers auth, invalid args.
            status = getattr(e, "status_code", None) or getattr(e, "code", None)
            msg = str(e)
            if status in (401, 403) or "API key" in msg or "PERMISSION_DENIED" in msg:
                raise LLMAuthError(msg) from e
            if status == 429 or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                raise LLMRateLimitError(msg) from e
            raise LLMError(msg) from e
        except genai_errors.ServerError as e:
            raise LLMTransientError(str(e)) from e
        except gax_exc.GoogleAPICallError as e:
            # Older transport errors that may slip through.
            if isinstance(e, gax_exc.Unauthenticated | gax_exc.PermissionDenied):
                raise LLMAuthError(str(e)) from e
            if isinstance(e, gax_exc.ResourceExhausted | gax_exc.TooManyRequests):
                raise LLMRateLimitError(str(e)) from e
            if isinstance(e, gax_exc.ServiceUnavailable | gax_exc.DeadlineExceeded):
                raise LLMTransientError(str(e)) from e
            raise LLMError(str(e)) from e
        except Exception as e:  # last-resort: wrap so the runner can decide
            raise LLMError(f"Gemini call failed: {e}") from e

        text = _extract_text(response)
        finish = _finish_reason(response)
        if not text:
            raise LLMSchemaValidationError(
                f"Gemini returned no text in response; finish_reason={finish!r}"
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            hint = ""
            if finish and "MAX_TOKENS" in str(finish):
                hint = (
                    " (response was truncated by max_output_tokens; "
                    "raise _MAX_OUTPUT_TOKENS_BY_VARIANT or split the page)"
                )
            raise LLMSchemaValidationError(
                f"Gemini response was not valid JSON{hint}: {e}\n"
                f"finish_reason={finish!r}\n--- raw (first 500 chars) ---\n{text[:500]}"
            ) from e


def _extract_text(response: Any) -> str:
    """Best-effort extraction of the JSON text from a Gemini response."""
    text = getattr(response, "text", None)
    if text:
        return text
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        if not content:
            continue
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "text", None):
                return part.text
    return ""


def _finish_reason(response: Any) -> str | None:
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        return getattr(candidates[0], "finish_reason", None)
    return None
