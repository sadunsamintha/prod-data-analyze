#!/usr/bin/env python3
"""Prepare dated GE-108 sent archives and analyze duplicate stringCode values."""

from __future__ import annotations

import argparse
from pathlib import Path

from ge108_data.ge108_sent import (
    extract_date,
    normalize_base_dir,
    run,
)


def prompt_for_date_query() -> str:
    return input("Enter the date to analyze (DD/MM/YYYY): ").strip()


def resolve_base_dir_interactively(candidate: Path) -> Path:
    resolved = normalize_base_dir(candidate)
    workspace_sent = candidate / "src" / "main" / "java" / "GE-108-data" / "data" / "products" / "sent"
    if workspace_sent.is_dir():
        return workspace_sent.resolve()
    while not resolved.is_dir():
        print(f"Configured sent folder not found or invalid: {resolved}")
        resolved = normalize_base_dir(
            Path(input("Please enter a valid sent folder path: ").strip())
        )
    return resolved.resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a dated sent/OKFILe workspace, copy and extract matching "
            ".data.zip files, and analyze duplicate stringCode values."
        )
    )
    parser.add_argument(
        "--sent-dir",
        help=(
            "Optional data/products/sent path or an ancestor containing it. "
            "If omitted or invalid, the script asks for the path."
        ),
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Query containing a date such as 'analyze data for 25/06/2026'.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    query = " ".join(args.query).strip()
    if not query:
        query = prompt_for_date_query()

    sent_candidate = Path(args.sent_dir).expanduser() if args.sent_dir else Path.cwd()
    sent_dir = resolve_base_dir_interactively(sent_candidate)
    run(query, sent_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
