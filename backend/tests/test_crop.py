from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.models import BBox
from app.pipeline.crop import (
    crop_region,
    denormalize_bbox,
    image_filename_for_page,
    slugify_korean,
)


def test_denormalize_square():
    b = BBox(x_min=100, y_min=200, x_max=900, y_max=800)
    assert denormalize_bbox(b, 1000, 1000) == (100, 200, 900, 800)


def test_denormalize_widescreen():
    b = BBox(x_min=0, y_min=0, x_max=1000, y_max=1000)
    assert denormalize_bbox(b, 1440, 810) == (0, 0, 1440, 810)


def test_denormalize_clamps_out_of_range_via_validation():
    # BBox enforces 0..1000, so denormalize itself never sees out-of-range.
    # But values right at the edges should produce edge-of-image coords.
    b = BBox(x_min=0, y_min=0, x_max=1000, y_max=1000)
    assert denormalize_bbox(b, 100, 100) == (0, 0, 100, 100)


def test_slugify_keeps_korean():
    assert slugify_korean("데이터 분석 모델이란?") == "데이터_분석_모델이란"


def test_slugify_truncates():
    long = "가" * 100
    assert len(slugify_korean(long, max_len=10)) == 10


def test_slugify_empty_yields_untitled():
    assert slugify_korean("???") == "untitled"


def test_image_filename_format():
    name = image_filename_for_page(7, "데이터 분석 모델은 어떻게 만들어질까?")
    assert name.startswith("07_")
    assert name.endswith(".png")
    assert "데이터" in name


def test_crop_region_writes_png(tmp_path: Path):
    src = tmp_path / "src.png"
    # 1000x1000 makes the math from 0..1000 normalized coords trivial.
    Image.new("RGB", (1000, 1000), (255, 0, 0)).save(src)
    bbox = BBox(x_min=100, y_min=100, x_max=900, y_max=700)
    dest = tmp_path / "out" / "crop.png"
    crop_region(src, bbox, dest)
    assert dest.exists()
    with Image.open(dest) as img:
        assert img.size == (800, 600)


def test_crop_region_creates_parent_dir(tmp_path: Path):
    src = tmp_path / "src.png"
    Image.new("RGB", (100, 100), (0, 0, 0)).save(src)
    dest = tmp_path / "deep" / "nested" / "out.png"
    crop_region(src, BBox(x_min=0, y_min=0, x_max=1000, y_max=1000), dest)
    assert dest.exists()
