"""PDF input/output: rasterization and per-page text extraction.

Uses PyMuPDF (fitz) for rasterization — works on Windows/Mac/Linux without
needing the poppler binaries. Pdfplumber is used for text extraction since it
preserves layout-aware ordering better than fitz's default text mode.
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber


class PDFValidationError(ValueError):
    """Raised when a file is not a usable PDF (corrupt, encrypted, too big, ...)."""


def get_page_count(pdf_path: str | Path) -> int:
    """Return the number of pages in a PDF."""
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def validate_pdf(
    pdf_path: str | Path,
    *,
    max_pages: int = 100,
    max_size_mb: int = 100,
) -> int:
    """Validate a PDF file and return its page count.

    Raises PDFValidationError on any policy violation.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise PDFValidationError(f"File not found: {path}")

    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > max_size_mb:
        raise PDFValidationError(
            f"PDF too large: {size_mb:.1f}MB > {max_size_mb}MB limit"
        )

    try:
        with fitz.open(path) as doc:
            if doc.is_encrypted:
                raise PDFValidationError("Encrypted PDFs are not supported")
            n = doc.page_count
    except fitz.FileDataError as e:
        raise PDFValidationError(f"Invalid or corrupt PDF: {e}") from e

    if n == 0:
        raise PDFValidationError("PDF has no pages")
    if n > max_pages:
        raise PDFValidationError(f"Too many pages: {n} > {max_pages} limit")
    return n


def rasterize_pages(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    dpi: int = 150,
    prefix: str = "page",
) -> list[Path]:
    """Render each page to PNG. Returns sorted list of paths.

    Output filenames: ``{prefix}-{N:03d}.png`` (1-indexed).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # fitz uses a 72 DPI base; we scale via Matrix.
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    paths: list[Path] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            target = out / f"{prefix}-{i:03d}.png"
            pix.save(target)
            paths.append(target)
    return paths


def extract_text_per_page(pdf_path: str | Path) -> list[str]:
    """Extract plain text per page using pdfplumber.

    Pdfplumber respects reading order better than fitz default for slide PDFs
    where text boxes are positioned visually. Empty pages return ''.
    """
    out: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            out.append(text)
    return out


def get_page_size(pdf_path: str | Path, page_index: int = 0) -> tuple[float, float]:
    """Return (width, height) of a page in PDF points (1/72 inch)."""
    with fitz.open(pdf_path) as doc:
        rect = doc[page_index].rect
        return float(rect.width), float(rect.height)
