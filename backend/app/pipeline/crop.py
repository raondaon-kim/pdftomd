"""bbox -> PIL crop helpers (docs/LLM_PROMPTS.md §7)."""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from app.models import BBox


def denormalize_bbox(
    bbox: BBox, image_width: int, image_height: int
) -> tuple[int, int, int, int]:
    """0~1000 normalized -> PIL crop tuple (left, top, right, bottom).

    Coordinates are clamped to the image bounds so a slightly-out-of-range LLM
    response still produces a valid crop.
    """
    left = max(0, min(image_width, int(bbox.x_min / 1000 * image_width)))
    top = max(0, min(image_height, int(bbox.y_min / 1000 * image_height)))
    right = max(0, min(image_width, int(bbox.x_max / 1000 * image_width)))
    bottom = max(0, min(image_height, int(bbox.y_max / 1000 * image_height)))
    if right <= left or bottom <= top:
        raise ValueError(
            f"Degenerate crop after denormalization: "
            f"{(left, top, right, bottom)} from {bbox} on {image_width}x{image_height}"
        )
    return left, top, right, bottom


def crop_region(src_image_path: str | Path, bbox: BBox, dest_path: str | Path) -> Path:
    """Crop ``src_image_path`` by normalized ``bbox`` and write PNG to ``dest_path``.

    Returns the destination path.
    """
    src = Path(src_image_path)
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(src) as img:
        box = denormalize_bbox(bbox, img.width, img.height)
        img.crop(box).save(dest, format="PNG", optimize=True)
    return dest


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------


_SLUG_RE = re.compile(r"[^\w가-힣\s]")
_WS_RE = re.compile(r"\s+")


def slugify_korean(text: str, max_len: int = 30) -> str:
    """Filename-safe slug allowing Korean characters.

    - Strips punctuation/symbols, keeps Hangul + alphanumerics + underscore
    - Collapses whitespace into ``_``
    - Truncates to ``max_len`` characters
    """
    s = _SLUG_RE.sub("", text)
    s = _WS_RE.sub("_", s.strip())
    return s[:max_len] or "untitled"


def image_filename_for_page(page_num: int, title: str) -> str:
    """e.g. ``07_데이터_분석_모델.png``."""
    return f"{page_num:02d}_{slugify_korean(title)}.png"
