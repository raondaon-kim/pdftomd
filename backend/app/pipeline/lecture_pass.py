"""Pass-1 orchestration: lecture-context extraction with retry + validation.

Per docs/LLM_PROMPTS.md §1.5 — strict mode means a hard failure of pass-1
fails the whole job. We retry transient errors a few times before giving up.
"""
from __future__ import annotations

import logging
import time

from app.models import LectureContext
from app.pipeline.providers.base import (
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMSchemaValidationError,
    LLMTransientError,
)

log = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_BACKOFF = 1.0  # seconds
DEFAULT_BACKOFF_MULTIPLIER = 2.0
PAGE_TEXT_TRIM_CHARS = 1000  # per-page cap before pass-1 (cost control)


def _trim_page_texts(texts: list[str], max_chars: int = PAGE_TEXT_TRIM_CHARS) -> list[str]:
    """Cap each page's text to ``max_chars`` to control pass-1 input size."""
    trimmed: list[str] = []
    for t in texts:
        if not t:
            trimmed.append("")
            continue
        if len(t) > max_chars:
            trimmed.append(t[:max_chars] + "\n…(truncated)")
        else:
            trimmed.append(t)
    return trimmed


def extract_lecture_context(
    provider: LLMProvider,
    *,
    page_texts: list[str],
    mosaic_image_bytes: bytes,
    total_pages: int,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
    sleep: callable = time.sleep,
) -> LectureContext:
    """Call ``provider.call_lecture_context`` with retry + outline validation.

    Strict semantics: after exhausting retries we re-raise the last LLMError
    so the runner can mark the whole job as failed.

    ``sleep`` is parameterized for tests.
    """
    trimmed = _trim_page_texts(page_texts)
    last_error: LLMError | None = None
    backoff = initial_backoff

    for attempt in range(1, max_retries + 1):
        try:
            ctx = provider.call_lecture_context(
                page_texts=trimmed,
                mosaic_image_bytes=mosaic_image_bytes,
                total_pages=total_pages,
            )
            # Outline page numbers must be in 1..total_pages with no dupes.
            ctx.validate_against_pdf(total_pages)
            log.info(
                "pass-1 ok on attempt %d (title=%r, %d outline entries, %d key terms)",
                attempt,
                ctx.title[:60],
                len(ctx.slide_outline),
                len(ctx.key_terms),
            )
            return ctx
        except (LLMSchemaValidationError, ValueError) as e:
            # Validation errors: retry once or twice — sometimes the model
            # produces a slightly malformed JSON / out-of-range page.
            last_error = (
                e if isinstance(e, LLMError) else LLMSchemaValidationError(str(e))
            )
            log.warning(
                "pass-1 validation failure (attempt %d/%d): %s",
                attempt,
                max_retries,
                e,
            )
        except (LLMRateLimitError, LLMTransientError) as e:
            last_error = e
            log.warning(
                "pass-1 transient failure (attempt %d/%d): %s: %s",
                attempt,
                max_retries,
                type(e).__name__,
                e,
            )
        except LLMError as e:
            # Non-retryable provider error (auth, etc.). Fail fast.
            log.error("pass-1 hard failure: %s: %s", type(e).__name__, e)
            raise

        if attempt < max_retries:
            log.info("pass-1 retrying in %.1fs", backoff)
            sleep(backoff)
            backoff *= backoff_multiplier

    assert last_error is not None
    log.error("pass-1 exhausted %d attempts; raising %s", max_retries, type(last_error).__name__)
    raise last_error
