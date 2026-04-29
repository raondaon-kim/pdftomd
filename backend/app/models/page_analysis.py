"""2-pass output: per-page analysis (docs/DATA_MODEL.md §1.3)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Classification = Literal["content", "section_divider", "cover", "decorative_only"]


class BBox(BaseModel):
    """Normalized bounding box (0-1000 coordinate system, top-left origin)."""

    model_config = ConfigDict(extra="forbid")

    x_min: float = Field(ge=0, le=1000)
    y_min: float = Field(ge=0, le=1000)
    x_max: float = Field(ge=0, le=1000)
    y_max: float = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def _check_order(self) -> "BBox":
        if self.x_max <= self.x_min:
            raise ValueError("x_max must be greater than x_min")
        if self.y_max <= self.y_min:
            raise ValueError("y_max must be greater than y_min")
        return self


class PageAnalysis(BaseModel):
    """LLM 2-pass output for a single page."""

    model_config = ConfigDict(extra="forbid")

    page_num: int = Field(ge=1)
    classification: Classification
    title: str
    markdown_body: str
    image_region: BBox | None = None
    image_caption: str | None = None
    reasoning: str

    # Processing-time metadata (populated after LLM call)
    image_filename: str | None = None
    llm_call_failed: bool = False

    @model_validator(mode="after")
    def _content_only_image(self) -> "PageAnalysis":
        # Only `content` pages may have an image_region.
        if self.classification != "content" and self.image_region is not None:
            raise ValueError(
                f"image_region is only allowed for 'content' pages, "
                f"got classification={self.classification!r}"
            )
        # Caption requires region.
        if self.image_caption and self.image_region is None:
            raise ValueError("image_caption requires image_region to be set")
        return self
