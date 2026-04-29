"""1-pass output: lecture-wide context (docs/DATA_MODEL.md §1.2)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SlideOutlineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)
    title: str
    one_line: str


class LectureContext(BaseModel):
    """Output of pass 1 — fed back into pass 2's system prompt."""

    model_config = ConfigDict(extra="forbid")

    title: str
    topic_summary: str
    slide_outline: list[SlideOutlineEntry]
    key_terms: list[str]
    domain_hints: str

    def validate_against_pdf(self, total_pages: int) -> None:
        """Strict checks per docs/DATA_MODEL.md §1.2.

        Raises ValueError if any constraint fails (used for retry decisions).
        """
        seen: set[int] = set()
        for entry in self.slide_outline:
            if entry.page < 1 or entry.page > total_pages:
                raise ValueError(
                    f"slide_outline page {entry.page} outside range 1..{total_pages}"
                )
            if entry.page in seen:
                raise ValueError(f"duplicate page {entry.page} in slide_outline")
            seen.add(entry.page)
        if len(self.slide_outline) > total_pages:
            raise ValueError(
                f"slide_outline length {len(self.slide_outline)} exceeds total_pages {total_pages}"
            )

    @model_validator(mode="after")
    def _non_empty(self) -> "LectureContext":
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.topic_summary.strip():
            raise ValueError("topic_summary must not be empty")
        if not self.slide_outline:
            raise ValueError("slide_outline must not be empty")
        return self
