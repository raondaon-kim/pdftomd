"""GET /health — minimal liveness check for the single-process backend."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.job_store import get_job_store

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "data_dir": str(settings.data_dir),
        "active_jobs": len(get_job_store().list()),
    }
