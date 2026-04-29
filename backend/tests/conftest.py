"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.fixture(scope="session")
def golden_pdf_path() -> Path:
    p = GOLDEN_DIR / "deepco_kdc_18" / "input.pdf"
    if not p.exists():
        pytest.skip(f"golden PDF not present at {p}")
    return p
