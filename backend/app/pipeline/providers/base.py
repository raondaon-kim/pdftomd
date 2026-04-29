"""LLMProvider Protocol + common error hierarchy (docs/LLM_PROMPTS.md §1.6)."""
from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import BaseModel

from app.models import LectureContext, PageAnalysis

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error hierarchy — provider-agnostic
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Base class for any provider-side failure."""


class LLMRateLimitError(LLMError):
    """429 / quota / TPM-RPM rate limits."""


class LLMAuthError(LLMError):
    """401 / 403 / bad API key."""


class LLMSchemaValidationError(LLMError):
    """Response did not match the requested JSON schema after retries."""


class LLMTransientError(LLMError):
    """Network blip / 5xx / timeout — typically retryable."""


# ---------------------------------------------------------------------------
# Provider info (used by /models endpoint and CLI listing)
# ---------------------------------------------------------------------------


class ProviderInfo(BaseModel):
    id: str
    display_name: str
    provider: str  # "anthropic" | "google"
    is_preview: bool
    enabled: bool
    estimated_cost_per_pdf_usd: float
    notes: str = ""


# ---------------------------------------------------------------------------
# Protocol the runner depends on
# ---------------------------------------------------------------------------


def patch_page_analysis_payload(raw: dict[str, Any], page_num: int) -> None:
    """Normalize a raw page-analysis payload before Pydantic validation.

    Both Claude and Gemini occasionally:
    - return a wrong ``page_num`` (the model is iterating over the lecture and
      forgets the input page). We overwrite with the truth.
    - emit ``image_region`` coordinates outside the 0..1000 range. We clamp.
    - attach an ``image_region`` to non-content pages, which our schema
      forbids. We strip it (and any companion ``image_caption``).

    Mutates ``raw`` in place.
    """
    raw.setdefault("page_num", page_num)
    if raw.get("page_num") != page_num:
        log.warning(
            "LLM returned page_num=%s for page %s; correcting",
            raw.get("page_num"),
            page_num,
        )
        raw["page_num"] = page_num

    region = raw.get("image_region")
    if isinstance(region, dict):
        for key in ("x_min", "y_min", "x_max", "y_max"):
            if key in region and isinstance(region[key], (int, float)):
                clamped = max(0, min(1000, region[key]))
                if clamped != region[key]:
                    log.warning(
                        "Clamping image_region.%s on page %d: %s -> %s",
                        key, page_num, region[key], clamped,
                    )
                    region[key] = clamped

    classification = raw.get("classification")
    if classification != "content" and raw.get("image_region") is not None:
        log.info(
            "Stripping image_region from page %d (classification=%s)",
            page_num,
            classification,
        )
        raw["image_region"] = None
        raw["image_caption"] = None

    # Caption is meaningless without a region; drop the orphan rather than
    # failing validation. Models occasionally emit a caption then null region.
    if raw.get("image_region") is None and raw.get("image_caption"):
        log.info(
            "Dropping orphan image_caption on page %d (no image_region)",
            page_num,
        )
        raw["image_caption"] = None


class LLMProvider(Protocol):
    """Minimal interface: pass-1 + pass-2 entry points.

    Concrete adapters MUST raise subclasses of ``LLMError`` for any failure so
    the runner can apply uniform retry/strict logic.
    """

    name: str
    display_name: str
    is_preview: bool

    def call_lecture_context(
        self,
        page_texts: list[str],
        mosaic_image_bytes: bytes,
        total_pages: int,
    ) -> LectureContext:
        """Pass 1 — extract lecture-wide context from mosaic + concatenated text."""
        ...

    def call_page_analysis(
        self,
        page_image_bytes: bytes,
        page_text: str,
        page_num: int,
        total_pages: int,
        context: LectureContext,
    ) -> PageAnalysis:
        """Pass 2 — analyze a single page given the lecture context."""
        ...
