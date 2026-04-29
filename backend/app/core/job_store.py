"""In-memory job store.

Single-process backend: a plain dict guarded by a lock. Designed to be swapped
out for Redis later by re-implementing the same interface (get/create/update).
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Iterator

from app.models import CurrentStep, Job, JobError, JobStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # --- lifecycle --------------------------------------------------------

    def create(
        self,
        *,
        job_id: str,
        model_id: str,
        pdf_filename: str,
        total_pages: int,
    ) -> Job:
        job = Job(
            job_id=job_id,
            status=JobStatus.QUEUED,
            model_id=model_id,
            pdf_filename=pdf_filename,
            total_pages=total_pages,
            created_at=_utcnow(),
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def delete(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    # --- mutations --------------------------------------------------------

    def mark_started(self, job_id: str) -> None:
        self._mutate(
            job_id,
            status=JobStatus.PROCESSING,
            started_at=_utcnow(),
        )

    def mark_done(self, job_id: str) -> None:
        self._mutate(
            job_id,
            status=JobStatus.DONE,
            progress_pct=100,
            finished_at=_utcnow(),
            error=None,
        )

    def mark_failed(self, job_id: str, *, code: str, message: str, page: int | None = None) -> None:
        self._mutate(
            job_id,
            status=JobStatus.FAILED,
            finished_at=_utcnow(),
            error=JobError(code=code, message=message, page=page),
        )

    def update_progress(
        self,
        job_id: str,
        *,
        step: CurrentStep | str | None = None,
        current_page: int | None = None,
        processed_pages: int | None = None,
        progress_pct: int | None = None,
    ) -> None:
        updates: dict = {}
        if step is not None:
            updates["current_step"] = (
                step if isinstance(step, CurrentStep) else CurrentStep(step)
            )
        if current_page is not None:
            updates["current_page"] = current_page
        if processed_pages is not None:
            updates["processed_pages"] = processed_pages
        if progress_pct is not None:
            updates["progress_pct"] = max(0, min(100, progress_pct))
        if updates:
            self._mutate(job_id, **updates)

    # --- internal ---------------------------------------------------------

    def _mutate(self, job_id: str, **updates) -> None:
        with self._lock:
            existing = self._jobs.get(job_id)
            if existing is None:
                return
            self._jobs[job_id] = existing.model_copy(update=updates)

    def __iter__(self) -> Iterator[Job]:
        with self._lock:
            yield from list(self._jobs.values())


# Module-level singleton — a single backend process owns one store.
_store: InMemoryJobStore | None = None


def get_job_store() -> InMemoryJobStore:
    global _store
    if _store is None:
        _store = InMemoryJobStore()
    return _store


def reset_job_store_for_tests() -> None:
    """Tests use this to start from a clean slate."""
    global _store
    _store = InMemoryJobStore()
