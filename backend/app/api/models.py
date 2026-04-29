"""GET /models — what the UI populates the radio buttons with."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.pipeline.providers import list_available_providers
from app.pipeline.providers.base import ProviderInfo

router = APIRouter(tags=["models"])


class ModelsResponse(BaseModel):
    models: list[ProviderInfo]


@router.get("/models", response_model=ModelsResponse)
async def get_models() -> ModelsResponse:
    return ModelsResponse(models=list_available_providers(get_settings()))
