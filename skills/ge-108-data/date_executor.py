#!/usr/bin/env python3
"""Safely profile local tabular datasets without modifying source data."""

from __future__ import annotations

import argparse
import codecs
import hashlib
import sys
from pathlib import Path
from typing import Sequence, TextIO

try:
    from ge108_data.analysis import compare_schemas, profile_dataset
    from ge108_data.inputs import (
        MAX_STDIN_BYTES,
        discover_files,
        load_path,
        load_stdin,
        validate_input_argument,
    )
    from ge108_data.ge108_sent import analyze_sent_archives
    from ge108_data.models import (
        AnalysisConfig,
        AnalysisError,
        AnalyzerError,
        DatasetReport,
        DatasetStatus,
        ExitCode,
        InvalidArgumentsError,
        OutlierMethod,
        ParseInputError,
        ReportFormat,
        RunReport,
    )
    from ge108_data.privacy import redact_message
    from ge108_data.reports import render, write_reports
except ImportError as exc:
    print(
        "Error: missing runtime dependency. Install with: "
        "python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(ExitCode.ANALYSIS_FAILURE) from exc


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(ExitCode.INVALID_ARGUMENTS, f"Error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = SafeArgumentParser(
        description="Analyze tabular data or GE-108 .data.zip sent archives.",
        epilog=(
            "Examples:\n"
            "  python date_executor.py --input data.csv\n"
            "  python date_executor.py --input data/ --recursive --format json\n"
            "  python date_executor.py --input - --format json < data.jsonl\n\n"
            "  python date_executor.py --sent-dir data/products/sent --date 25/06/2026\n\n"
            "Exit statuses: 0 success, 2 invalid arguments, 3 missing input, "
            "4 unreadable input, 5 unsupported format, 6 parsing failure, "
            "7 analysis failure, 8 output failure, 9 export failure, "
            "10 partial success."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        action="append",
        metavar="PATH",
        help="File or folder to analyze; repeat for multiple inputs, or use - for stdin",
    )
    parser.add_argument(
        "--sent-dir",
        type=Path,
        help="GE-108 data/products/sent directory (or an ancestor containing it)",
    )
    parser.add_argument(
        "--date",
        help="GE-108 sent-file date in DD/MM/YYYY or DD-MM-YYYY format",
    )
    parser.add_argument("--output", type=Path, help="Directory for persisted reports")
    parser.add_argument(
        "--format",
        dest="report_format",
        choices=[item.value for item in ReportFormat],
        default=ReportFormat.TEXT.value,
        help="Report format (default: text)",
    )
    parser.add_argument("--recursive", action="store_true", help="Search folder inputs recursively")
    parser.add_argument("--sheet", help="Excel worksheet name or zero-based index")
    parser.add_argument("--delimiter", help=r"CSV/TSV delimiter override; use \t for tab")
    parser.add_argument("--encoding", default="utf-8-sig", help="Text encoding (default: utf-8-sig)")
    parser.add_argument("--columns", help="Comma-separated columns to analyze")
    parser.add_argument("--group-by", help=argparse.SUPPRESS)
    parser.add_argument("--target", help=argparse.SUPPRESS)
    parser.add_argument(
        "--sample-size",
        type=int,
        default=100_000,
        help="Maximum rows retained for expensive analyses (default: 100000)",
    )
    parser.add_argument(
        "--max-category-values",
        type=int,
        default=20,
        help="Maximum displayed values per categorical column (default: 20)",
    )
    parser.add_argument(
        "--outlier-method",
        choices=[item.value for item in OutlierMethod],
        default=OutlierMethod.IQR.value,
        help="Outlier indicator method (default: iqr)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace existing generated reports")
    parser.add_argument("--verbose", action="store_true", help="Print selected files and diagnostics to stderr")
    return parser


def config_from_args(args: argparse.Namespace) -> AnalysisConfig:
    if args.sent_dir is not None or args.date is not None:
        if args.sent_dir is None or args.date is None:
            raise InvalidArgumentsError("--sent-dir and --date must be supplied together")
        if args.input:
            raise InvalidArgumentsError("--input cannot be combined with --sent-dir/--date")
    elif not args.input:
        raise InvalidArgumentsError("provide --input, or provide --sent-dir together with --date")
    if args.sample_size <= 0:
        raise InvalidArgumentsError("--sample-size must be a positive integer")
    if not 1 <= args.max_category_values <= 1000:
        raise InvalidArgumentsError("--max-category-values must be between 1 and 1000")
    if args.group_by:
        raise InvalidArgumentsError("--group-by is planned for a later version and is not yet supported")
    if args.target:
        raise InvalidArgumentsError("--target is planned for a later version and is not yet supported")
    try:
        codecs.lookup(args.encoding)
    except LookupError as exc:
        raise InvalidArgumentsError(f'unknown encoding: "{args.encoding}"') from exc
    delimiter = args.delimiter
    if delimiter == r"\t":
        delimiter = "\t"
    if delimiter is not None and len(delimiter) != 1:
        raise InvalidArgumentsError("--delimiter must be exactly one character")
    columns = tuple(item.strip() for item in (args.columns or "").split(",") if item.strip())
    if len(columns) != len(set(columns)):
        raise InvalidArgumentsError("--columns must not contain duplicates")
    inputs = args.input or ()
    if inputs.count("-") > 1 or ("-" in inputs and len(inputs) > 1):
        raise InvalidArgumentsError("standard input cannot be repeated or combined with path inputs")
    return AnalysisConfig(
        inputs=tuple(inputs),
        output=args.output,
        report_format=ReportFormat(args.report_format),
        recursive=args.recursive,
        sheet=args.sheet,
        delimiter=delimiter,
        encoding=args.encoding,
        columns=columns,
        sample_size=args.sample_size,
        max_category_values=args.max_category_values,
        outlier_method=OutlierMethod(args.outlier_method),
        overwrite=args.overwrite,
        verbose=args.verbose,
    )


def _error_report(supplied: str, error: AnalyzerError) -> DatasetReport:
    return DatasetReport(
        source={
            "supplied_path": supplied,
            "file_name": Path(supplied).name if supplied != "-" else "stdin",
            "detected_format": None,
            "source_id": hashlib.sha256(supplied.encode("utf-8")).hexdigest()[:12],
            "sheet": None,
            "size_bytes": None,
        },
        status=DatasetStatus.ERROR,
        errors=[
            {
                "code": int(error.exit_code),
                "type": type(error).__name__,
                "message": redact_message(str(error)),
                "path": error.path,
            }
        ],
    )


def read_stdin_bounded(stdin: TextIO, encoding: str) -> str:
    chunks: list[str] = []
    total_bytes = 0
    while True:
        chunk = stdin.read(64 * 1024)
        if not chunk:
            break
        total_bytes += len(chunk.encode(encoding.replace("-sig", ""), errors="strict"))
        if total_bytes > MAX_STDIN_BYTES:
            raise ParseInputError(
                f"standard input exceeds the {MAX_STDIN_BYTES} byte safety limit",
                path="-",
            )
        chunks.append(chunk)
    return "".join(chunks)


def execute(
    config: AnalysisConfig,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> tuple[RunReport, ExitCode]:
    reports: list[DatasetReport] = []
    failure_codes: list[ExitCode] = []
    for supplied in config.inputs:
        try:
            source = validate_input_argument(supplied, Path.cwd())
            if source.is_stdin:
                reports.append(
                    profile_dataset(
                        load_stdin(read_stdin_bounded(stdin, config.encoding), config),
                        config,
                    )
                )
            else:
                paths = discover_files(
                    source,
                    recursive=config.recursive,
                    output_dir=config.output,
                )
                if config.verbose:
                    for path in paths:
                        print(f"Selected: {path}", file=stderr)
                for path in paths:
                    file_source = source
                    if source.path and source.path.is_dir():
                        file_source = type(source)(
                            supplied=str(path), path=path, root=source.path
                        )
                    try:
                        reports.append(profile_dataset(load_path(path, file_source, config), config))
                    except AnalyzerError as error:
                        reports.append(_error_report(file_source.supplied, error))
                        failure_codes.append(error.exit_code)
                        print(f"Error: {redact_message(str(error))}", file=stderr)
                    except Exception as unexpected:
                        error = AnalysisError(
                            f'analysis failed for input: "{file_source.supplied}"',
                            path=file_source.supplied,
                        )
                        reports.append(_error_report(file_source.supplied, error))
                        failure_codes.append(error.exit_code)
                        print(f"Error: {redact_message(str(error))}", file=stderr)
                        if config.verbose:
                            print(f"Cause: {type(unexpected).__name__}", file=stderr)
        except AnalyzerError as error:
            reports.append(_error_report(supplied, error))
            failure_codes.append(error.exit_code)
            print(f"Error: {redact_message(str(error))}", file=stderr)
            if error.path:
                print("Please provide a corrected or accessible path.", file=stderr)
        except Exception as unexpected:
            error = AnalysisError(
                f'analysis failed for input: "{supplied}"', path=supplied
            )
            reports.append(_error_report(supplied, error))
            failure_codes.append(error.exit_code)
            print(f"Error: {redact_message(str(error))}", file=stderr)
            if config.verbose:
                print(f"Cause: {type(unexpected).__name__}", file=stderr)

    run_report = RunReport(reports)
    comparisons = compare_schemas(reports)
    if comparisons:
        for dataset in reports:
            if dataset.status == DatasetStatus.SUCCESS:
                dataset.inferences["schema_comparisons"] = comparisons
                break
    try:
        paths = write_reports(run_report, config)
    except AnalyzerError as error:
        print(f"Error: {redact_message(str(error))}", file=stderr)
        return run_report, error.exit_code
    for path in paths:
        print(f"Created: {path}", file=stderr)
    stdout.write(render(run_report, config.report_format))

    if failure_codes and run_report.successful_count:
        return run_report, ExitCode.PARTIAL_SUCCESS
    if failure_codes:
        return run_report, failure_codes[0]
    return run_report, ExitCode.SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = config_from_args(args)
        if args.sent_dir is not None:
            result = analyze_sent_archives(
                args.sent_dir,
                args.date,
                overwrite=args.overwrite,
            )
            print(f"Sent directory: {result.sent_dir}")
            print(f"Date directory: {result.date_dir}")
            print(f"OKFILe directory: {result.okfile_dir}")
            print(f"Copied archives: {len(result.copied_archives)}")
            print(f"Copied other files: {len(result.copied_files)}")
            print(f"Extracted files: {len(result.extracted_files)}")
            print(f"Scanned .data.ok files: {result.scanned_files}")
            print(f"Total production count: {result.total_product_count}")
            print(f"Duplicate groups: {result.duplicate_code_count}")
            print(f"Duplicate occurrences: {result.duplicate_entry_count}")
            print(f"Same-status groups: {result.same_status_groups}")
            print(f"Mixed-status groups: {result.mixed_status_groups}")
            for report in result.reports:
                print(f"Created: {report}")
            return int(ExitCode.SUCCESS)
        _, exit_code = execute(config, sys.stdin, sys.stdout, sys.stderr)
        return int(exit_code)
    except AnalyzerError as error:
        print(f"Error: {redact_message(str(error))}", file=sys.stderr)
        return int(error.exit_code)
    except KeyboardInterrupt:
        print("Error: analysis interrupted", file=sys.stderr)
        return int(ExitCode.ANALYSIS_FAILURE)


if __name__ == "__main__":
    raise SystemExit(main())
