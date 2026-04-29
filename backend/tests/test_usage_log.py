"""Tests for the per-job token usage logger."""
from __future__ import annotations

import json
from pathlib import Path

from app.pipeline.usage_log import append_usage_record


def test_creates_log_dir_and_appends_jsonl(tmp_path: Path):
    log_dir = tmp_path / "nested" / "logs"
    append_usage_record(
        log_dir=log_dir,
        pdf_filename="lecture.pdf",
        model_id="gpt-5.4-mini",
        input_tokens=12345,
        output_tokens=6789,
        pages=28,
        ok=True,
    )
    log_file = log_dir / "usage.log"
    assert log_file.is_file()
    line = log_file.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["pdf"] == "lecture.pdf"
    assert record["model"] == "gpt-5.4-mini"
    assert record["input_tokens"] == 12345
    assert record["output_tokens"] == 6789
    assert record["total_tokens"] == 12345 + 6789
    assert record["pages"] == 28
    assert record["ok"] is True
    assert "ts" in record


def test_appends_multiple_lines(tmp_path: Path):
    log_dir = tmp_path / "logs"
    for i in range(3):
        append_usage_record(
            log_dir=log_dir,
            pdf_filename=f"file_{i}.pdf",
            model_id="claude-haiku-4-5",
            input_tokens=100 * i,
            output_tokens=50 * i,
            pages=10,
            ok=True,
        )
    lines = (log_dir / "usage.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    records = [json.loads(line) for line in lines]
    assert [r["pdf"] for r in records] == ["file_0.pdf", "file_1.pdf", "file_2.pdf"]


def test_records_failures_with_error(tmp_path: Path):
    log_dir = tmp_path / "logs"
    append_usage_record(
        log_dir=log_dir,
        pdf_filename="broken.pdf",
        model_id="gemini-3-flash",
        input_tokens=200,
        output_tokens=0,
        pages=0,
        ok=False,
        error="LLMSchemaValidationError: bad json",
    )
    record = json.loads((log_dir / "usage.log").read_text(encoding="utf-8").strip())
    assert record["ok"] is False
    assert record["error"].startswith("LLMSchemaValidationError")
    assert record["pages"] == 0


def test_korean_filename_roundtrip(tmp_path: Path):
    log_dir = tmp_path / "logs"
    append_usage_record(
        log_dir=log_dir,
        pdf_filename="강의자료.pdf",
        model_id="gpt-5.4-mini",
        input_tokens=1,
        output_tokens=2,
        pages=1,
        ok=True,
    )
    record = json.loads((log_dir / "usage.log").read_text(encoding="utf-8").strip())
    assert record["pdf"] == "강의자료.pdf"
