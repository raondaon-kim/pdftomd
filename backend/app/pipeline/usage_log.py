"""Per-job token usage logging.

Each completed pipeline run appends one JSON line to ``<data_dir>/logs/usage.log``
so operators can see how many tokens each PDF consumed per model. Format is
intentionally simple: open the file in any text editor, or aggregate with
``jq`` / ``pandas.read_json(lines=True)``.

Sample line::

    {"ts": "2026-04-29T15:21:30+00:00", "job_id": "550e...", "pdf": "강의자료.pdf",
     "model": "gpt-5.4-mini", "input_tokens": 12345, "output_tokens": 6789,
     "total_tokens": 19134, "pages": 28,
     "input_cost_usd": 0.00926, "output_cost_usd": 0.03055,
     "total_cost_usd": 0.03981, "ok": true}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


# Vendor list-prices in USD per 1,000,000 tokens. Sourced from each vendor's
# pricing page in April 2026 — review periodically as prices drift.
#
# Keep these as a single source of truth; the runner, CLI, and any future
# dashboard all read from MODEL_PRICES_USD_PER_M.
MODEL_PRICES_USD_PER_M: dict[str, dict[str, float]] = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "gemini-2-5-flash": {"input": 0.30, "output": 2.50},
    "gemini-3-flash": {"input": 0.50, "output": 3.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
}


def estimate_cost_usd(
    model_id: str, input_tokens: int, output_tokens: int
) -> tuple[float, float, float] | None:
    """Return (input_cost, output_cost, total_cost) in USD, or None if model unknown.

    Costs are floats rounded to 6 decimals so a sub-cent sub-job entry doesn't
    silently become 0.0 in the JSONL output.
    """
    rates = MODEL_PRICES_USD_PER_M.get(model_id)
    if rates is None:
        return None
    in_cost = round(input_tokens * rates["input"] / 1_000_000, 6)
    out_cost = round(output_tokens * rates["output"] / 1_000_000, 6)
    return in_cost, out_cost, round(in_cost + out_cost, 6)


def append_usage_record(
    *,
    log_dir: Path,
    pdf_filename: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    pages: int,
    ok: bool,
    job_id: str | None = None,
    error: str | None = None,
) -> None:
    """Append one JSON line to ``log_dir/usage.log``.

    Failures here MUST NOT crash the pipeline. We log a warning and move on.
    """
    record: dict[str, object] = {
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if job_id:
        record["job_id"] = job_id
    record["pdf"] = pdf_filename
    record["model"] = model_id
    record["input_tokens"] = int(input_tokens)
    record["output_tokens"] = int(output_tokens)
    record["total_tokens"] = int(input_tokens) + int(output_tokens)
    record["pages"] = int(pages)

    cost = estimate_cost_usd(model_id, int(input_tokens), int(output_tokens))
    if cost is not None:
        in_cost, out_cost, total_cost = cost
        record["input_cost_usd"] = in_cost
        record["output_cost_usd"] = out_cost
        record["total_cost_usd"] = total_cost

    record["ok"] = bool(ok)
    if error:
        record["error"] = error

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with (log_dir / "usage.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as e:
        log.warning("Failed to write usage log: %s", e)
