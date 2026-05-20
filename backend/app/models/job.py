"""Job state model (docs/DATA_MODEL.md §1.1)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class CurrentStep(str, Enum):
    VALIDATING = "validating"
    RASTERIZING = "rasterizing"
    EXTRACTING_TEXT = "extracting_text"
    EXTRACTING_CONTEXT = "extracting_context"  # 1패스
    ANALYZING_PAGE = "analyzing_page"          # 2패스
    CROPPING = "cropping"
    PACKAGING = "packaging"


class JobError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    page: int | None = None


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: JobStatus
    model_id: str
    pdf_filename: str = ""
    total_pages: int = 0
    processed_pages: int = 0
    progress_pct: int = Field(default=0, ge=0, le=100)
    current_step: CurrentStep | None = None
    current_page: int | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: JobError | None = None
    callback_url: str | None = None
