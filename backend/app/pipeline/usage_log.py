"""Per-job token usage logging.

Each completed pipeline run appends one JSON line to ``<data_dir>/logs/usage.log``
so operators can see how many tokens each PDF consumed per model. Format is
intentionally simple: open the file in any text editor, or aggregate with
``jq`` / ``pandas.read_json(lines=True)``.

Sample line::

    {"ts": "2026-04-29T15:21:30+00:00", "pdf": "lecture.pdf",
     "model": "gpt-5.4-mini", "input_tokens": 12345, "output_tokens": 6789,
     "total_tokens": 19134, "pages": 28, "ok": true}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def append_usage_record(
    *,
    log_dir: Path,
    pdf_filename: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    pages: int,
    ok: bool,
    error: str | None = None,
) -> None:
    """Append one JSON line to ``log_dir/usage.log``.

    Failures here MUST NOT crash the pipeline. We log a warning and move on.
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pdf": pdf_filename,
        "model": model_id,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(input_tokens) + int(output_tokens),
        "pages": int(pages),
        "ok": bool(ok),
    }
    if error:
        record["error"] = error

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with (log_dir / "usage.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as e:
        log.warning("Failed to write usage log: %s", e)
