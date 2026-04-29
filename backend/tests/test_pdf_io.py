from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.pdf_io import (
    PDFValidationError,
    extract_text_per_page,
    get_page_count,
    get_page_size,
    rasterize_pages,
    validate_pdf,
)


def test_get_page_count(golden_pdf_path: Path):
    assert get_page_count(golden_pdf_path) == 28


def test_validate_pdf_ok(golden_pdf_path: Path):
    assert validate_pdf(golden_pdf_path, max_pages=100, max_size_mb=100) == 28


def test_validate_pdf_rejects_missing(tmp_path: Path):
    with pytest.raises(PDFValidationError):
        validate_pdf(tmp_path / "missing.pdf")


def test_validate_pdf_rejects_oversize(golden_pdf_path: Path):
    with pytest.raises(PDFValidationError, match="too large"):
        validate_pdf(golden_pdf_path, max_size_mb=1)


def test_validate_pdf_rejects_too_many_pages(golden_pdf_path: Path):
    with pytest.raises(PDFValidationError, match="Too many pages"):
        validate_pdf(golden_pdf_path, max_pages=10)


def test_get_page_size(golden_pdf_path: Path):
    w, h = get_page_size(golden_pdf_path)
    # PowerPoint widescreen 16:9 default
    assert (w, h) == (1440.0, 810.0)


def test_extract_text_per_page(golden_pdf_path: Path):
    texts = extract_text_per_page(golden_pdf_path)
    assert len(texts) == 28
    # p.6 introduces the data analysis model concept
    p6 = texts[5]
    assert "데이터" in p6
    assert "분석" in p6
    assert "지도학습" in p6


def test_rasterize_pages_writes_pngs(tmp_path: Path, golden_pdf_path: Path):
    out = rasterize_pages(golden_pdf_path, tmp_path, dpi=72)
    assert len(out) == 28
    for p in out:
        assert p.exists()
        assert p.suffix == ".png"
        assert p.stat().st_size > 0
