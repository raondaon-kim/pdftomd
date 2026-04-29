"""End-to-end pipeline test with a fake LLM provider.

Verifies that runner.run_pipeline produces a coherent ZIP for a real PDF when
the provider returns deterministic responses for both pass-1 and pass-2.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from app.models import BBox, LectureContext, PageAnalysis, SlideOutlineEntry
from app.pipeline import runner


class _FakeProvider:
    """Returns canned PageAnalysis values per page; never makes a network call."""

    name = "claude-haiku-4-5"
    display_name = "Claude Haiku 4.5"
    is_preview = False

    def __init__(self):
        self.calls: list[int] = []
        self.context_calls: int = 0

    def call_lecture_context(self, *, page_texts, mosaic_image_bytes, total_pages) -> LectureContext:
        self.context_calls += 1
        return LectureContext(
            title="Fake Lecture",
            topic_summary="A fake summary used in the runner integration test.",
            slide_outline=[
                SlideOutlineEntry(page=i, title=f"p.{i}", one_line="line")
                for i in range(1, total_pages + 1)
            ],
            key_terms=["FAKE", "TEST"],
            domain_hints="testing",
        )

    def call_page_analysis(
        self,
        *,
        page_image_bytes: bytes,
        page_text: str,
        page_num: int,
        total_pages: int,
        context: LectureContext,
    ) -> PageAnalysis:
        self.calls.append(page_num)
        # Mimic the test.pdf classification distribution roughly
        cls = "content"
        if page_num == 1 or page_num == total_pages:
            cls = "cover"
        elif page_num in (2, 5, 8, 13, 16, 20, 26):
            cls = "section_divider"
        elif page_num in (19, 22):
            cls = "decorative_only"
        image_region = None
        caption = None
        if cls == "content" and page_num == 7:
            # Attach an image only on one page so we can assert on it.
            image_region = BBox(x_min=60, y_min=160, x_max=970, y_max=950)
            caption = "five-step process"
        return PageAnalysis(
            page_num=page_num,
            classification=cls,
            title=f"page {page_num}",
            markdown_body=f"body for {page_num}" if cls == "content" else "",
            image_region=image_region,
            image_caption=caption,
            reasoning="fake",
        )


def test_run_pipeline_end_to_end(tmp_path: Path, golden_pdf_path: Path):
    provider = _FakeProvider()
    out = tmp_path / "out"
    progress_events: list[tuple[str, int]] = []

    def progress(*, step: str, current: int = 0, total: int = 0, pct: int = 0):
        progress_events.append((step, pct))

    result = runner.run_pipeline(
        pdf_path=golden_pdf_path,
        output_dir=out,
        provider=provider,
        dpi=72,  # speed up tests
        on_progress=progress,
    )

    # 1. Pass-1 ran exactly once; all 28 pages went through pass-2.
    assert provider.context_calls == 1
    assert len(provider.calls) == 28
    assert provider.calls == list(range(1, 29))

    # 2. Outputs exist.
    assert result.content_md.exists()
    assert result.zip_path.exists()

    # 3. content.md has the expected structure.
    md = result.content_md.read_text(encoding="utf-8")
    # Header now uses LectureContext.title from the fake pass-1.
    assert md.startswith("# Fake Lecture")
    assert "FAKE, TEST" in md  # key terms appear
    assert "## 슬라이드 6 — page 6" in md  # content page
    assert "## 슬라이드 2 — page 2" in md  # section_divider page (header only)
    assert "슬라이드 1 " not in md  # cover skipped
    assert "![five-step process](images/07_page_7.png)" in md

    # 4. Cropped image exists in zip.
    with zipfile.ZipFile(result.zip_path) as zf:
        names = set(zf.namelist())
    assert "content.md" in names
    assert "images/07_page_7.png" in names

    # 5. Scratch pages dir should be cleaned up.
    assert not (out / "pages").exists()

    # 6. Progress events covered every step.
    seen_steps = {s for s, _ in progress_events}
    assert {"validating", "rasterizing", "extracting_text", "analyzing_page", "packaging"} <= seen_steps
