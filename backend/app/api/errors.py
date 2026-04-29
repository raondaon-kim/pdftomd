"""Common error response shape (per docs/API.md §공통)."""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def http_error(status_code: int, code: str, message: str, *, details: dict | None = None) -> HTTPException:
    """Raise an HTTPException whose body matches ErrorResponse."""
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": details}},
    )
