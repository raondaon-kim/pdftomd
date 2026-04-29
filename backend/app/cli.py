"""Command-line entrypoint for the PDF -> ZIP pipeline.

Usage:
    python -m app.cli INPUT.pdf -o ./out --model claude-haiku-4-5
    python -m app.cli INPUT.pdf --list-models
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from app.core.config import Settings
from app.pipeline import runner
from app.pipeline.providers import (
    ALL_MODEL_IDS,
    LLMError,
    list_available_providers,
    make_provider,
)
from app.pipeline.pdf_io import PDFValidationError


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Convert a slide PDF into self-contained markdown + ZIP.",
    )
    parser.add_argument("pdf", type=Path, nargs="?", help="Path to input PDF")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("./out"),
        help="Directory to write content.md / images / result.zip",
    )
    parser.add_argument(
        "--model",
        choices=ALL_MODEL_IDS,
        help="LLM model id (defaults to first model with a configured key)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=None,
        help="Page rasterization DPI (default from settings)",
    )
    parser.add_argument(
        "--keep-pages",
        action="store_true",
        help="Keep the temporary pages/ directory (debugging)",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Print models and which are enabled, then exit",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="-v=INFO, -vv=DEBUG (default WARNING)",
    )
    return parser


def _setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def _print_models(settings: Settings) -> int:
    infos = list_available_providers(settings)
    print(f"{'ID':<20} {'enabled':<8} {'preview':<8} {'cost/PDF':<10} {'name'}")
    for info in infos:
        print(
            f"{info.id:<20} "
            f"{'yes' if info.enabled else 'no':<8} "
            f"{'yes' if info.is_preview else 'no':<8} "
            f"${info.estimated_cost_per_pdf_usd:<9.2f} "
            f"{info.display_name}"
        )
    return 0


def _pick_default_model(settings: Settings) -> str | None:
    for info in list_available_providers(settings):
        if info.enabled:
            return info.id
    return None


def _stderr_progress(*, step: str, current: int = 0, total: int = 0, pct: int = 0) -> None:
    if step == "analyzing_page" and total:
        sys.stderr.write(
            f"\r[{pct:3d}%] {step}: page {current}/{total}      "
        )
    else:
        sys.stderr.write(f"\r[{pct:3d}%] {step}                    ")
    sys.stderr.flush()


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    settings = Settings()

    if args.list_models:
        return _print_models(settings)

    if args.pdf is None:
        parser.error("PDF path is required (or pass --list-models)")
    if not args.pdf.exists():
        parser.error(f"PDF not found: {args.pdf}")

    model_id = args.model or _pick_default_model(settings)
    if model_id is None:
        print(
            "ERROR: No LLM API key configured. Set ANTHROPIC_API_KEY or GEMINI_API_KEY.",
            file=sys.stderr,
        )
        return 2

    try:
        provider = make_provider(model_id, settings)
    except (ValueError, NotImplementedError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(
        f"input:    {args.pdf}\n"
        f"output:   {args.output_dir}\n"
        f"model:    {model_id}",
        file=sys.stderr,
    )

    started = time.monotonic()
    try:
        result = runner.run_pipeline(
            pdf_path=args.pdf,
            output_dir=args.output_dir,
            provider=provider,
            dpi=args.dpi or settings.render_dpi,
            max_pages=settings.max_pdf_pages,
            max_size_mb=settings.max_pdf_size_mb,
            keep_pages_dir=args.keep_pages,
            on_progress=_stderr_progress,
        )
    except PDFValidationError as e:
        sys.stderr.write("\n")
        print(f"ERROR (PDF validation): {e}", file=sys.stderr)
        return 3
    except LLMError as e:
        sys.stderr.write("\n")
        print(f"ERROR (LLM): {type(e).__name__}: {e}", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        return 130

    elapsed = time.monotonic() - started
    sys.stderr.write("\n")
    print(
        f"\nDone in {elapsed:.1f}s\n"
        f"  pages:    {len(result.pages)}\n"
        f"  content:  {result.content_md}\n"
        f"  zip:      {result.zip_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
