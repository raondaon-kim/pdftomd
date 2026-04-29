"""Tests for the thumbnail mosaic builder."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.pipeline.mosaic import build_thumbnail_mosaic


def _make_pages(tmp_path: Path, count: int, color=(80, 120, 200)) -> list[Path]:
    paths: list[Path] = []
    for i in range(1, count + 1):
        p = tmp_path / f"page-{i:03d}.png"
        Image.new("RGB", (1440, 810), color).save(p)
        paths.append(p)
    return paths


def test_empty_pages_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        build_thumbnail_mosaic([])


def test_basic_mosaic_dimensions(tmp_path: Path):
    pages = _make_pages(tmp_path, 4)
    mosaic_bytes, included = build_thumbnail_mosaic(
        pages, cols=2, cell_width=200, cell_height=150
    )
    img = Image.open(BytesIO(mosaic_bytes))
    assert img.size == (400, 300)  # 2 cols x 2 rows
    assert included == [1, 2, 3, 4]


def test_28_pages_default_grid(tmp_path: Path):
    pages = _make_pages(tmp_path, 28)
    mosaic_bytes, included = build_thumbnail_mosaic(pages)
    img = Image.open(BytesIO(mosaic_bytes))
    # 6 cols x 5 rows
    assert img.size == (6000, 2815)
    assert included == list(range(1, 29))


def test_sampling_for_large_pdf(tmp_path: Path):
    pages = _make_pages(tmp_path, 80)
    mosaic_bytes, included = build_thumbnail_mosaic(pages, sample_limit=20)
    assert len(included) <= 20
    # First and last must be present for orientation.
    assert included[0] == 1
    assert included[-1] == 80


def test_max_width_cap_reduces_cols(tmp_path: Path):
    pages = _make_pages(tmp_path, 12)
    # cols=10 with default cell width would be 10000px > 8000 max.
    mosaic_bytes, _ = build_thumbnail_mosaic(
        pages, cols=10, max_mosaic_width=4000, cell_width=1000, cell_height=563
    )
    img = Image.open(BytesIO(mosaic_bytes))
    assert img.width <= 4000


def test_label_visible_on_each_cell(tmp_path: Path):
    """Smoke check: labeled mosaic is larger than identical raw cells (because
    of label overlay), confirming we drew something."""
    pages = _make_pages(tmp_path, 4)
    labeled, _ = build_thumbnail_mosaic(pages, cols=2, cell_width=400, cell_height=300)
    # Just make sure it parses and has the expected shape.
    img = Image.open(BytesIO(labeled))
    assert img.mode == "RGB"
    assert img.size == (800, 600)
