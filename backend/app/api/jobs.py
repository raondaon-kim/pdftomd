"""Job endpoints: upload, polling, download."""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.api.errors import http_error
from app.api.worker import run_pipeline_job
from app.core.config import get_settings
from app.core.job_store import get_job_store
from app.models import Job
from app.pipeline.pdf_io import PDFValidationError, validate_pdf
from app.pipeline.providers import ALL_MODEL_IDS, list_available_providers

log = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Magic bytes for a PDF: %PDF
_PDF_MAGIC = b"%PDF"


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


class CreateJobResponse(BaseModel):
    job_id: str
    status: str
    total_pages: int
    model: str
    created_at: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    model: str
    total_pages: int
    processed_pages: int
    progress_pct: int
    current_step: str | None
    current_page: int | None
    started_at: str | None
    finished_at: str | None
    error: dict | None


def _job_to_status(job: Job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status.value,
        model=job.model_id,
        total_pages=job.total_pages,
        processed_pages=job.processed_pages,
        progress_pct=job.progress_pct,
        current_step=job.current_step.value if job.current_step else None,
        current_page=job.current_page,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
        error=job.error.model_dump() if job.error else None,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=CreateJobResponse)
async def create_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    model: str = Form(...),
) -> CreateJobResponse:
    """Accept a PDF and a model id; kick off background processing."""
    settings = get_settings()
    store = get_job_store()

    # 1. Validate model id and key availability.
    if model not in ALL_MODEL_IDS:
        raise http_error(400, "INVALID_MODEL", f"Unknown model id: {model}")
    available = {info.id: info.enabled for info in list_available_providers(settings)}
    if not available.get(model, False):
        raise http_error(
            400,
            "MODEL_NOT_AVAILABLE",
            f"Model '{model}' is not enabled (API key missing)",
        )

    # 2. Validate file shape (extension + magic bytes).
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise http_error(400, "INVALID_FILE_TYPE", "File must be a .pdf")
    head = await file.read(4)
    if head != _PDF_MAGIC:
        raise http_error(400, "INVALID_FILE_TYPE", "File is not a valid PDF (bad magic bytes)")

    # 3. Persist to disk under a fresh job id.
    job_id = str(uuid.uuid4())
    settings.ensure_data_dirs()
    upload_dir = settings.uploads_dir / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    target_path = upload_dir / "input.pdf"

    rest = await file.read()
    target_path.write_bytes(head + rest)

    size_mb = target_path.stat().st_size / (1024 * 1024)
    if size_mb > settings.max_pdf_size_mb:
        target_path.unlink(missing_ok=True)
        upload_dir.rmdir()
        raise http_error(
            400,
            "FILE_TOO_LARGE",
            f"PDF is {size_mb:.1f}MB; limit is {settings.max_pdf_size_mb}MB",
        )

    # 4. Validate PDF structure + page count.
    try:
        total_pages = validate_pdf(
            target_path,
            max_pages=settings.max_pdf_pages,
            max_size_mb=settings.max_pdf_size_mb,
        )
    except PDFValidationError as e:
        target_path.unlink(missing_ok=True)
        upload_dir.rmdir()
        # Differentiate page-count vs other validation errors so the UI can
        # show specific messages.
        msg = str(e)
        code = "TOO_MANY_PAGES" if "Too many pages" in msg else "INVALID_PDF"
        raise http_error(400, code, msg)

    # 5. Register and enqueue.
    output_dir = settings.outputs_dir / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    job = store.create(
        job_id=job_id,
        model_id=model,
        pdf_filename=file.filename,
        total_pages=total_pages,
    )
    background_tasks.add_task(
        run_pipeline_job,
        job_id=job_id,
        pdf_path=str(target_path),
        output_dir=str(output_dir),
        model_id=model,
    )

    return CreateJobResponse(
        job_id=job.job_id,
        status=job.status.value,
        total_pages=job.total_pages,
        model=job.model_id,
        created_at=job.created_at.isoformat(),
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    job = get_job_store().get(job_id)
    if job is None:
        raise http_error(404, "JOB_NOT_FOUND", f"Job {job_id} not found")
    return _job_to_status(job)


@router.get("/{job_id}/download")
async def download_zip(job_id: str):
    job = get_job_store().get(job_id)
    if job is None:
        raise http_error(404, "JOB_NOT_FOUND", f"Job {job_id} not found")
    if job.status.value != "done":
        raise http_error(404, "RESULT_NOT_READY", "Job has not finished yet")

    settings = get_settings()
    zip_path = settings.outputs_dir / job_id / "result.zip"
    if not zip_path.exists():
        raise http_error(404, "RESULT_NOT_READY", "Result file is not available")

    safe_name = (job.pdf_filename or "result").rsplit(".", 1)[0]
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"{safe_name}.zip",
    )


@router.get("/{job_id}/content")
async def get_content_md(job_id: str):
    """Convenience endpoint for the frontend preview pane."""
    job = get_job_store().get(job_id)
    if job is None:
        raise http_error(404, "JOB_NOT_FOUND", f"Job {job_id} not found")
    if job.status.value != "done":
        raise http_error(404, "RESULT_NOT_READY", "Job has not finished yet")

    settings = get_settings()
    md_path = settings.outputs_dir / job_id / "content.md"
    if not md_path.exists():
        raise http_error(404, "RESULT_NOT_READY", "content.md is not available")
    return FileResponse(md_path, media_type="text/markdown; charset=utf-8")


@router.get("/{job_id}/images/{filename}")
async def get_image(job_id: str, filename: str):
    """Serve cropped reference images so the frontend preview can render them."""
    job = get_job_store().get(job_id)
    if job is None:
        raise http_error(404, "JOB_NOT_FOUND", f"Job {job_id} not found")
    # Path traversal guard: only allow simple filenames.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise http_error(400, "INVALID_FILENAME", "Filename must not contain path separators")

    settings = get_settings()
    img_path = settings.outputs_dir / job_id / "images" / filename
    if not img_path.exists():
        raise http_error(404, "IMAGE_NOT_FOUND", f"{filename} not in images/")
    return FileResponse(img_path, media_type="image/png")


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str):
    settings = get_settings()
    store = get_job_store()
    if not store.delete(job_id):
        raise http_error(404, "JOB_NOT_FOUND", f"Job {job_id} not found")
    # Best-effort cleanup of disk artifacts.
    for sub in (settings.uploads_dir / job_id, settings.outputs_dir / job_id):
        if sub.exists():
            shutil.rmtree(sub, ignore_errors=True)
    return JSONResponse(status_code=204, content=None)
