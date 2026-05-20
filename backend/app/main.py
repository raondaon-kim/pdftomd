"""FastAPI application entry point.

Single-process backend: pipeline runs via BackgroundTasks in the same process,
state lives in an in-memory job store. No Redis, no separate worker.

Run locally:
    cd backend
    uvicorn app.main:app --host 127.0.0.1 --port 9007 --reload
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import health, jobs, models
from app.api.errors import ErrorBody, ErrorResponse
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_data_dirs()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    app = FastAPI(
        title="PDF Slide Extractor",
        description=(
            "LLM Vision으로 강의 슬라이드 PDF를 자급자족 마크다운으로 변환합니다."
        ),
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # Reshape HTTPException bodies into the {"error": {...}} envelope.
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        # If the detail dict already matches our envelope, pass through.
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error=ErrorBody(code="HTTP_ERROR", message=str(exc.detail))
            ).model_dump(),
        )

    # Last-resort error mapper so the UI always sees a structured body.
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception):
        logging.exception("unhandled exception")
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=ErrorBody(
                    code="INTERNAL_ERROR",
                    message=f"{type(exc).__name__}: {exc}",
                )
            ).model_dump(),
        )

    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(jobs.router)

    return app


app = create_app()
