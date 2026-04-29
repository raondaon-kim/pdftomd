"""Static catalog of supported LLM model IDs (docs/LLM_PROMPTS.md §1.4)."""
from __future__ import annotations

from app.pipeline.providers.base import ProviderInfo

# Internal IDs used in the API (`POST /jobs` model field, CLI flag, etc.).
CLAUDE_HAIKU_4_5 = "claude-haiku-4-5"
GEMINI_2_5_FLASH = "gemini-2-5-flash"
GEMINI_3_FLASH = "gemini-3-flash"
GPT_5_MINI = "gpt-5-mini"
GPT_5_4_MINI = "gpt-5.4-mini"

ALL_MODEL_IDS = [
    CLAUDE_HAIKU_4_5,
    GEMINI_2_5_FLASH,
    GEMINI_3_FLASH,
    GPT_5_MINI,
    GPT_5_4_MINI,
]

# Vendor-side model IDs (sent in API requests). Update when new releases come out.
VENDOR_MODEL_IDS: dict[str, str] = {
    CLAUDE_HAIKU_4_5: "claude-haiku-4-5",
    GEMINI_2_5_FLASH: "gemini-2.5-flash",
    GEMINI_3_FLASH: "gemini-3-flash-preview",
    GPT_5_MINI: "gpt-5-mini",
    GPT_5_4_MINI: "gpt-5.4-mini",
}


def get_metadata(model_id: str, *, enabled: bool) -> ProviderInfo:
    """Return display metadata for a model. ``enabled`` reflects key availability."""
    if model_id == CLAUDE_HAIKU_4_5:
        return ProviderInfo(
            id=model_id,
            display_name="Claude Haiku 4.5",
            provider="anthropic",
            is_preview=False,
            enabled=enabled,
            estimated_cost_per_pdf_usd=0.20,
            notes="한국어와 안정성 균형. 비전 양호.",
        )
    if model_id == GEMINI_2_5_FLASH:
        return ProviderInfo(
            id=model_id,
            display_name="Gemini 2.5 Flash",
            provider="google",
            is_preview=False,
            enabled=enabled,
            estimated_cost_per_pdf_usd=0.10,
            notes="가장 저렴. 한국어 양호.",
        )
    if model_id == GEMINI_3_FLASH:
        return ProviderInfo(
            id=model_id,
            display_name="Gemini 3 Flash",
            provider="google",
            is_preview=False,
            enabled=enabled,
            estimated_cost_per_pdf_usd=0.20,
            notes="속도 약 2배. 멀티모달 이해 강세 — 블록 코드/복잡 다이어그램에 유리.",
        )
    if model_id == GPT_5_MINI:
        return ProviderInfo(
            id=model_id,
            display_name="GPT-5 mini",
            provider="openai",
            is_preview=False,
            enabled=enabled,
            estimated_cost_per_pdf_usd=0.30,
            notes="GPT-5 시리즈 mini. 비전·추론 안정적, 검증된 멀티모달.",
        )
    if model_id == GPT_5_4_MINI:
        return ProviderInfo(
            id=model_id,
            display_name="GPT-5.4 mini",
            provider="openai",
            is_preview=False,
            enabled=enabled,
            estimated_cost_per_pdf_usd=0.45,
            notes="비전·추론 모두 강세. GPT-5 mini 대비 약 2배 빠르고 멀티모달 이해 향상.",
        )
    raise ValueError(f"Unknown model id: {model_id!r}")
