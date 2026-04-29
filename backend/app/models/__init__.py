"""Pydantic models shared across the pipeline."""
from app.models.job import CurrentStep, Job, JobError, JobStatus
from app.models.lecture_context import LectureContext, SlideOutlineEntry
from app.models.page_analysis import BBox, Classification, PageAnalysis

__all__ = [
    "BBox",
    "Classification",
    "CurrentStep",
    "Job",
    "JobError",
    "JobStatus",
    "LectureContext",
    "PageAnalysis",
    "SlideOutlineEntry",
]
