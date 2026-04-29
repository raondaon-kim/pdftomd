"""Assemble final content.md and zip the output (docs/DATA_MODEL.md §5)."""
from __future__ import annotations

import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

from app.models import LectureContext, PageAnalysis
from app.pipeline.providers.registry import get_metadata


# ---------------------------------------------------------------------------
# Markdown assembly
# ---------------------------------------------------------------------------


def _format_header(
    *,
    pdf_filename: str,
    total_pages: int,
    model_id: str,
    context: LectureContext | None,
    extracted_on: date | None = None,
) -> str:
    """Top-of-document metadata block + lecture summary."""
    extracted_on = extracted_on or date.today()
    if context is not None:
        title = context.title.strip() or pdf_filename
    else:
        title = pdf_filename

    try:
        meta = get_metadata(model_id, enabled=True)
        model_label = meta.display_name + (" (preview)" if meta.is_preview else "")
    except ValueError:
        model_label = model_id

    lines: list[str] = [
        f"# {title}",
        "",
        f"> 추출 일시: {extracted_on.isoformat()}",
        f"> 원본 PDF: {pdf_filename}",
        f"> 원본 페이지 수: {total_pages}",
        f"> 분석 모델: {model_label}",
        "",
    ]
    if context is not None and context.topic_summary.strip():
        lines += ["## 강의 요약", "", context.topic_summary.strip(), ""]
        if context.domain_hints.strip():
            lines += [f"**도메인**: {context.domain_hints.strip()}", ""]
        if context.key_terms:
            lines += ["**핵심 용어**: " + ", ".join(context.key_terms), ""]
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _format_page(page: PageAnalysis) -> str | None:
    """Render a single page block. Return ``None`` for cover pages (skipped)."""
    if page.classification == "cover":
        return None

    body_lines: list[str] = [f"## 슬라이드 {page.page_num} — {page.title.strip()}", ""]

    body = (page.markdown_body or "").strip()
    if page.classification == "section_divider":
        # Per docs/DATA_MODEL.md §5: section dividers keep only the H2 title.
        if body:
            body_lines += [body, ""]
    elif page.classification == "decorative_only":
        if body:
            body_lines += [body, ""]
        else:
            body_lines.append("")
    else:  # content
        if body:
            body_lines += [body, ""]
        if page.image_region is not None and page.image_filename:
            caption = (page.image_caption or page.title or "").strip()
            body_lines += [f"![{caption}](images/{page.image_filename})", ""]

    return "\n".join(body_lines).rstrip() + "\n"


def build_markdown(
    pages: list[PageAnalysis],
    *,
    pdf_filename: str,
    model_id: str,
    context: LectureContext | None = None,
    extracted_on: date | None = None,
) -> str:
    """Combine header + page sections, separated by ``---`` horizontal rules."""
    total_pages = max((p.page_num for p in pages), default=0)
    parts: list[str] = [
        _format_header(
            pdf_filename=pdf_filename,
            total_pages=total_pages,
            model_id=model_id,
            context=context,
            extracted_on=extracted_on,
        )
    ]
    sections = [_format_page(p) for p in sorted(pages, key=lambda p: p.page_num)]
    visible = [s for s in sections if s is not None]
    parts.append("\n---\n\n".join(visible))
    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# ZIP packaging
# ---------------------------------------------------------------------------


def write_content_md(output_dir: str | Path, markdown: str) -> Path:
    """Write ``content.md`` under ``output_dir`` and return the path."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "content.md"
    target.write_text(markdown, encoding="utf-8")
    return target


def build_zip(output_dir: str | Path, *, zip_name: str = "result.zip") -> Path:
    """Zip ``content.md`` + ``images/`` from ``output_dir`` into ``output_dir/zip_name``.

    Internal scratch directories (e.g. ``pages/``) are NOT included.
    Returns the zip path.
    """
    out = Path(output_dir)
    target = out / zip_name
    md = out / "content.md"
    if not md.exists():
        raise FileNotFoundError(f"content.md not found in {out}")

    images_dir = out / "images"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(md, arcname="content.md")
        if images_dir.is_dir():
            for img in sorted(images_dir.iterdir()):
                if img.is_file():
                    zf.write(img, arcname=f"images/{img.name}")
    return target


# ---------------------------------------------------------------------------
# Convenience: full package step
# ---------------------------------------------------------------------------


def package_result(
    pages: list[PageAnalysis],
    *,
    output_dir: str | Path,
    pdf_filename: str,
    model_id: str,
    context: LectureContext | None = None,
    extracted_on: date | None = None,
) -> tuple[Path, Path]:
    """Write content.md, return (content_md_path, zip_path)."""
    md = build_markdown(
        pages,
        pdf_filename=pdf_filename,
        model_id=model_id,
        context=context,
        extracted_on=extracted_on,
    )
    md_path = write_content_md(output_dir, md)
    zip_path = build_zip(output_dir)
    return md_path, zip_path


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
