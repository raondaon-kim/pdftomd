"""Background pipeline worker invoked via FastAPI BackgroundTasks.

Wraps ``runner.run_pipeline`` with:
- progress reporting into ``InMemoryJobStore``
- exception handling that maps pipeline errors to ``JobError`` codes
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.job_store import InMemoryJobStore, get_job_store
from app.pipeline.pdf_io import PDFValidationError
from app.pipeline.providers import LLMAuthError, LLMError, make_provider
from app.pipeline.runner import run_pipeline

log = logging.getLogger(__name__)


def _make_progress_reporter(store: InMemoryJobStore, job_id: str):
    def _report(*, step: str, current: int = 0, total: int = 0, pct: int = 0) -> None:
        store.update_progress(
            job_id,
            step=step,
            current_page=current or None,
            processed_pages=current or None,
            progress_pct=pct,
        )

    return _report


def run_pipeline_job(
    *,
    job_id: str,
    pdf_path: str,
    output_dir: str,
    model_id: str,
) -> None:
    """Run the full pipeline for ``job_id``. Designed for BackgroundTasks.

    Updates the job_store throughout. Catches every exception and records it
    on the job as ``failed`` — never re-raises (BackgroundTasks would swallow
    it anyway, and the client sees status via polling).
    """
    settings = get_settings()
    store = get_job_store()
    store.mark_started(job_id)

    try:
        provider = make_provider(model_id, settings)
    except (ValueError, NotImplementedError) as e:
        log.exception("provider construction failed for job %s", job_id)
        store.mark_failed(job_id, code="MODEL_NOT_AVAILABLE", message=str(e))
        return
    except LLMAuthError as e:
        store.mark_failed(job_id, code="LLM_AUTH_ERROR", message=str(e))
        return

    # Fetch the user-visible original filename so the usage log records what
    # the operator actually uploaded, not the stable on-disk name "input.pdf".
    job = store.get(job_id)
    original_pdf_filename = job.pdf_filename if job is not None else None

    try:
        run_pipeline(
            pdf_path=Path(pdf_path),
            output_dir=Path(output_dir),
            provider=provider,
            dpi=settings.render_dpi,
            max_pages=settings.max_pdf_pages,
            max_size_mb=settings.max_pdf_size_mb,
            on_progress=_make_progress_reporter(store, job_id),
            usage_log_dir=settings.data_dir / "logs",
            original_pdf_filename=original_pdf_filename,
            job_id=job_id,
        )
    except PDFValidationError as e:
        log.warning("PDF validation failed for job %s: %s", job_id, e)
        store.mark_failed(job_id, code="INVALID_PDF", message=str(e))
        return
    except LLMAuthError as e:
        store.mark_failed(job_id, code="LLM_AUTH_ERROR", message=str(e))
        return
    except LLMError as e:
        log.exception("LLM error for job %s", job_id)
        store.mark_failed(job_id, code="LLM_API_ERROR", message=str(e))
        return
    except Exception as e:  # noqa: BLE001 — catch-all for background task safety
        log.exception("pipeline crashed for job %s", job_id)
        store.mark_failed(job_id, code="INTERNAL_ERROR", message=f"{type(e).__name__}: {e}")
        return

    store.mark_done(job_id)
    log.info("job %s done", job_id)
