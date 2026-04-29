"""Tests for the per-job token usage logger."""
from __future__ import annotations

import json
import math
from pathlib import Path

from app.pipeline.usage_log import (
    MODEL_PRICES_USD_PER_M,
    append_usage_record,
    estimate_cost_usd,
)


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
        job_id="job-abc-123",
    )
    log_file = log_dir / "usage.log"
    assert log_file.is_file()
    line = log_file.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["pdf"] == "lecture.pdf"
    assert record["job_id"] == "job-abc-123"
    assert record["model"] == "gpt-5.4-mini"
    assert record["input_tokens"] == 12345
    assert record["output_tokens"] == 6789
    assert record["total_tokens"] == 12345 + 6789
    assert record["pages"] == 28
    assert record["ok"] is True
    # Cost fields are present and approximately correct (gpt-5.4-mini is
    # $0.75/M input, $4.50/M output -> ~$0.0399 here). Comparison uses the
    # same rounding the writer applies (6 decimals).
    assert record["input_cost_usd"] == round(12345 * 0.75 / 1_000_000, 6)
    assert record["output_cost_usd"] == round(6789 * 4.50 / 1_000_000, 6)
    assert math.isclose(
        record["total_cost_usd"],
        record["input_cost_usd"] + record["output_cost_usd"],
        abs_tol=1e-6,
    )
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


def test_estimate_cost_per_known_model():
    # Hand-checked numbers: 1M input + 1M output should equal input rate +
    # output rate exactly per the price table.
    for model_id, rates in MODEL_PRICES_USD_PER_M.items():
        cost = estimate_cost_usd(model_id, 1_000_000, 1_000_000)
        assert cost is not None
        in_cost, out_cost, total = cost
        assert math.isclose(in_cost, rates["input"], abs_tol=1e-6)
        assert math.isclose(out_cost, rates["output"], abs_tol=1e-6)
        assert math.isclose(total, rates["input"] + rates["output"], abs_tol=1e-6)


def test_estimate_cost_unknown_model_returns_none():
    assert estimate_cost_usd("unknown-model", 100, 200) is None


def test_unknown_model_skips_cost_fields(tmp_path: Path):
    log_dir = tmp_path / "logs"
    append_usage_record(
        log_dir=log_dir,
        pdf_filename="x.pdf",
        model_id="not-in-table",
        input_tokens=10,
        output_tokens=20,
        pages=1,
        ok=True,
    )
    record = json.loads((log_dir / "usage.log").read_text(encoding="utf-8").strip())
    assert "total_cost_usd" not in record
    assert "input_cost_usd" not in record
