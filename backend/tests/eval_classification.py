"""Compare a content.md output against backend/tests/golden/<slug>/expected.json.

Usage:
    python -m tests.eval_classification \
        --content-md ../output/content.md \
        --golden tests/golden/deepco_kdc_18/expected.json \
        [--report-out ../output/classification_report.md]

Marked classification logic mirrors docs/DATA_MODEL.md §5: pages absent from
content.md are treated as 'cover'; pages with empty body after the H2 header
are 'section_divider'; very short bodies without images are 'decorative_only';
everything else is 'content'.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEADER_RE = re.compile(r"^## 슬라이드 (\d+) — (.+?)$", re.MULTILINE)


def split_pages(md: str) -> dict[int, tuple[str, str]]:
    """Return {page_num: (title, body)} from content.md."""
    parts = re.split(r"^---$", md, flags=re.MULTILINE)
    out: dict[int, tuple[str, str]] = {}
    for part in parts:
        m = HEADER_RE.search(part)
        if not m:
            continue
        page = int(m.group(1))
        title = m.group(2).strip()
        body = part[m.end():].strip()
        out[page] = (title, body)
    return out


def classify_observed(visible: dict[int, tuple[str, str]], page: int) -> str:
    if page not in visible:
        return "cover"
    _title, body = visible[page]
    if not body.strip():
        return "section_divider"
    short = len(body) < 200
    has_image = "![" in body
    if short and not has_image:
        return "decorative_only"
    return "content"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--content-md", type=Path, required=True)
    p.add_argument("--golden", type=Path, required=True)
    p.add_argument("--report-out", type=Path, default=None)
    args = p.parse_args(argv)

    md = args.content_md.read_text(encoding="utf-8")
    expected = json.loads(args.golden.read_text(encoding="utf-8"))
    visible = split_pages(md)

    rows: list[tuple[int, str, str, bool, str]] = []
    matches = 0
    for entry in expected["pages"]:
        page = entry["page_num"]
        e_class = entry["classification"]
        o_class = classify_observed(visible, page)
        title = visible.get(page, ("", ""))[0]
        ok = e_class == o_class
        if ok:
            matches += 1
        rows.append((page, e_class, o_class, ok, title))

    total = len(rows)
    pct = 100.0 * matches / total if total else 0.0

    lines = [
        "# 분류 비교 — golden vs content.md",
        "",
        f"- 골든: `{args.golden}`",
        f"- 결과: `{args.content_md}`",
        f"- **정확도: {matches}/{total} ({pct:.0f}%)**",
        "",
        "| page | expected | observed | match | title |",
        "|---:|---|---|:---:|---|",
    ]
    for page, e, o, ok, title in rows:
        lines.append(f"| {page} | {e} | {o} | {'✓' if ok else '✗'} | {title} |")
    report = "\n".join(lines) + "\n"

    # Write to stdout via UTF-8 bytes to dodge Windows cp949 console issues.
    sys.stdout.buffer.write(report.encode("utf-8", errors="replace"))
    if args.report_out:
        args.report_out.write_text(report, encoding="utf-8")
        sys.stderr.write(f"wrote report: {args.report_out}\n")

    return 0 if matches == total else 1


if __name__ == "__main__":
    sys.exit(main())
