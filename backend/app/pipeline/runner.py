"""End-to-end pipeline runner (CLI/worker entrypoint).

Orchestrates pass-1 (lecture context) + pass-2 (per-page analysis). Pass-1 is
strict: if it fails after retries, the whole job fails (docs/LLM_PROMPTS §1.5.7).
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.models import LectureContext, PageAnalysis
from app.pipeline import crop, packager, pdf_io
from app.pipeline.lecture_pass import extract_lecture_context
from app.pipeline.mosaic import build_thumbnail_mosaic
from app.pipeline.providers.base import LLMProvider
from app.pipeline.usage_log import append_usage_record

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress reporting hook (Redis writer in M2 plugs in here)
# ---------------------------------------------------------------------------


class ProgressReporter(Protocol):
    def __call__(self, *, step: str, current: int = 0, total: int = 0, pct: int = 0) -> None: ...


def _noop_reporter(**_: object) -> None:
    return None


@dataclass(slots=True)
class PipelineResult:
    output_dir: Path
    content_md: Path
    zip_path: Path
    context: LectureContext
    pages: list[PageAnalysis]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def run_pipeline(
    *,
    pdf_path: str | Path,
    output_dir: str | Path,
    provider: LLMProvider,
    dpi: int = 150,
    max_pages: int = 100,
    max_size_mb: int = 100,
    keep_pages_dir: bool = False,
    on_progress: ProgressReporter | None = None,
    usage_log_dir: str | Path | None = None,
) -> PipelineResult:
    """Run the full PDF -> ZIP pipeline.

    Steps mirror docs/ARCHITECTURE.md §4. M1.a uses a dummy LectureContext.

    ``usage_log_dir`` (when provided) receives a JSONL line summarising the
    job's token usage on completion *and* on failure. The log entry uses the
    PDF's original filename so operators can correlate cost to source.
    """
    report = on_progress or _noop_reporter

    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    usage_log_dir = Path(usage_log_dir) if usage_log_dir is not None else None

    pdf_filename = pdf_path.stem  # e.g. "deepco_kdc_18"

    # 1. validate
    report(step="validating", pct=1)
    try:
        total_pages = pdf_io.validate_pdf(pdf_path, max_pages=max_pages, max_size_mb=max_size_mb)
    except Exception as e:
        # Even validation failures get logged so we can track which uploads
        # never reached an LLM call. Token counts are zero in that case.
        if usage_log_dir is not None:
            append_usage_record(
                log_dir=usage_log_dir,
                pdf_filename=pdf_path.name,
                model_id=provider.name,
                input_tokens=getattr(provider, "total_input_tokens", 0),
                output_tokens=getattr(provider, "total_output_tokens", 0),
                pages=0,
                ok=False,
                error=f"{type(e).__name__}: {e}",
            )
        raise
    log.info("validated PDF: %d pages", total_pages)

    try:
        # 2. rasterize
        report(step="rasterizing", pct=2)
        pages_dir = output_dir / "pages"
        pages_dir.mkdir(exist_ok=True)
        page_pngs = pdf_io.rasterize_pages(pdf_path, pages_dir, dpi=dpi)
        log.info("rasterized %d pages at %d dpi", len(page_pngs), dpi)

        # 3. extract per-page text
        report(step="extracting_text", pct=3)
        page_texts = pdf_io.extract_text_per_page(pdf_path)
        if len(page_texts) != total_pages:
            log.warning(
                "text page count (%d) != fitz page count (%d); proceeding with min",
                len(page_texts),
                total_pages,
            )

        # 4. lecture context (pass 1) — strict
        report(step="extracting_context", pct=4)
        log.info("building thumbnail mosaic for pass-1 (%d pages)", total_pages)
        mosaic_bytes, included = build_thumbnail_mosaic(page_pngs)
        if len(included) != total_pages:
            log.info(
                "pass-1 mosaic uses %d/%d sampled pages; outline still validated against full count",
                len(included),
                total_pages,
            )
        context = extract_lecture_context(
            provider,
            page_texts=page_texts,
            mosaic_image_bytes=mosaic_bytes,
            total_pages=total_pages,
        )
        report(step="extracting_context", pct=5)

        # 5. per-page pass-2 analysis
        pages: list[PageAnalysis] = []
        images_dir = output_dir / "images"
        images_dir.mkdir(exist_ok=True)
        for i, png_path in enumerate(page_pngs, start=1):
            report(
                step="analyzing_page",
                current=i,
                total=total_pages,
                pct=5 + int((i / total_pages) * 90),
            )
            analysis = provider.call_page_analysis(
                page_image_bytes=_read_bytes(png_path),
                page_text=page_texts[i - 1] if i - 1 < len(page_texts) else "",
                page_num=i,
                total_pages=total_pages,
                context=context,
            )
            # 6. crop image if requested
            if (
                analysis.classification == "content"
                and analysis.image_region is not None
            ):
                filename = crop.image_filename_for_page(analysis.page_num, analysis.title)
                try:
                    crop.crop_region(png_path, analysis.image_region, images_dir / filename)
                    analysis.image_filename = filename
                except ValueError as e:
                    log.warning("crop failed on page %d: %s — skipping image", i, e)
                    analysis.image_region = None
                    analysis.image_caption = None
            pages.append(analysis)
            log.info(
                "page %d/%d done (classification=%s, image=%s)",
                i,
                total_pages,
                analysis.classification,
                "yes" if analysis.image_filename else "no",
            )

        # 7. assemble markdown + zip
        report(step="packaging", pct=98)
        md_path, zip_path = packager.package_result(
            pages,
            output_dir=output_dir,
            pdf_filename=pdf_filename,
            model_id=provider.name,
            context=context,
        )

        # 8. cleanup scratch
        if not keep_pages_dir:
            shutil.rmtree(pages_dir, ignore_errors=True)

        report(step="packaging", pct=100)
    except Exception as e:
        # LLM/SDK or assembly failure mid-job — still record any tokens spent.
        if usage_log_dir is not None:
            append_usage_record(
                log_dir=usage_log_dir,
                pdf_filename=pdf_path.name,
                model_id=provider.name,
                input_tokens=getattr(provider, "total_input_tokens", 0),
                output_tokens=getattr(provider, "total_output_tokens", 0),
                pages=total_pages,
                ok=False,
                error=f"{type(e).__name__}: {e}",
            )
        raise

    # 9. token usage log (best-effort; never raises)
    if usage_log_dir is not None:
        append_usage_record(
            log_dir=usage_log_dir,
            pdf_filename=pdf_path.name,
            model_id=provider.name,
            input_tokens=getattr(provider, "total_input_tokens", 0),
            output_tokens=getattr(provider, "total_output_tokens", 0),
            pages=total_pages,
            ok=True,
        )

    return PipelineResult(
        output_dir=output_dir,
        content_md=md_path,
        zip_path=zip_path,
        context=context,
        pages=pages,
    )
