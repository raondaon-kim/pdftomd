"""Build a thumbnail mosaic of all PDF pages for the pass-1 LLM call.

Per docs/LLM_PROMPTS.md §1.5.1:
- Each page becomes a thumbnail cell (~1000x563 = 16:9 at 100 DPI).
- ``cols`` cells per row (default 6). 28 pages -> 5 rows.
- Page number label (``p.N``) drawn in the top-left of each cell.
- Final mosaic width capped to ~8000 px so the image fits Vision API limits.
- For PDFs with > ``sample_limit`` pages we sample evenly to keep size sane.
"""
from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Tuneable constants
DEFAULT_COLS = 6
DEFAULT_CELL_WIDTH = 1000
DEFAULT_CELL_HEIGHT = 563  # 16:9
MAX_MOSAIC_WIDTH = 8000  # px
DEFAULT_SAMPLE_LIMIT = 50  # if total pages > this, sample evenly

# Font lookup: ship-friendly fallbacks. Labels are ASCII so any TTF works.
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/malgun.ttf",  # Windows
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Debian/Ubuntu
    "/Library/Fonts/Arial.ttf",  # macOS
    "arial.ttf",
]


def _load_label_font(size: int) -> ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _select_pages(page_pngs: list[Path], limit: int) -> tuple[list[Path], list[int]]:
    """Pick at most ``limit`` evenly-spaced pages.

    Returns (selected paths, original 1-indexed page numbers).
    """
    n = len(page_pngs)
    if n <= limit:
        return list(page_pngs), list(range(1, n + 1))
    # Even spacing: indices 0, n/limit, 2n/limit, ...
    step = n / limit
    indices = [int(i * step) for i in range(limit)]
    # Always keep first and last for orientation.
    if 0 not in indices:
        indices[0] = 0
    if n - 1 not in indices:
        indices[-1] = n - 1
    indices = sorted(set(indices))[:limit]
    selected = [page_pngs[i] for i in indices]
    page_nums = [i + 1 for i in indices]
    return selected, page_nums


def _resize_cell(img: Image.Image, width: int, height: int) -> Image.Image:
    """Letterbox-fit ``img`` into a (width, height) cell on white background."""
    src_w, src_h = img.size
    scale = min(width / src_w, height / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    cell = Image.new("RGB", (width, height), "white")
    cell.paste(resized, ((width - new_w) // 2, (height - new_h) // 2))
    return cell


def build_thumbnail_mosaic(
    page_pngs: list[Path],
    *,
    cols: int = DEFAULT_COLS,
    cell_width: int = DEFAULT_CELL_WIDTH,
    cell_height: int = DEFAULT_CELL_HEIGHT,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    max_mosaic_width: int = MAX_MOSAIC_WIDTH,
) -> tuple[bytes, list[int]]:
    """Combine pages into one labeled grid PNG.

    Returns ``(png_bytes, included_page_numbers)``.
    Caller passes ``page_pngs`` in 1-indexed order; ``included_page_numbers``
    tells the caller which subset (if any) was sampled.
    """
    if not page_pngs:
        raise ValueError("page_pngs must not be empty")

    selected, page_nums = _select_pages(page_pngs, sample_limit)

    # Adjust cols upward if the requested cols would blow past max_mosaic_width.
    while cols * cell_width > max_mosaic_width and cols > 1:
        cols -= 1
    # Then adjust cell size downward if even cols=1 would be too wide.
    if cols * cell_width > max_mosaic_width:
        scale = max_mosaic_width / (cols * cell_width)
        cell_width = max(1, int(cell_width * scale))
        cell_height = max(1, int(cell_height * scale))
    # Re-grow cols if many pages (for compactness): aim near sqrt aspect.
    while cols < len(selected) and (cols + 1) * cell_width <= max_mosaic_width and \
            math.ceil(len(selected) / cols) > cols:
        cols += 1

    rows = math.ceil(len(selected) / cols)
    canvas_w = cols * cell_width
    canvas_h = rows * cell_height
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")

    label_font = _load_label_font(size=max(20, cell_height // 14))
    draw = ImageDraw.Draw(canvas)

    for i, (png_path, page_num) in enumerate(zip(selected, page_nums)):
        row, col = divmod(i, cols)
        x = col * cell_width
        y = row * cell_height
        with Image.open(png_path) as img:
            cell = _resize_cell(img.convert("RGB"), cell_width, cell_height)
            canvas.paste(cell, (x, y))
        # Label in top-left with white halo for legibility.
        label = f"p.{page_num}"
        pad = 6
        draw.rectangle(
            (x + pad, y + pad, x + pad + 110, y + pad + 38),
            fill=(255, 255, 255, 220),
            outline=(0, 0, 0),
        )
        draw.text((x + pad + 6, y + pad + 4), label, fill=(0, 0, 0), font=label_font)

    buffer = BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), page_nums
