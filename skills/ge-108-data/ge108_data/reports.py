"""Deterministic report rendering and protected output writing."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .models import AnalysisConfig, DatasetReport, OutputError, ReportFormat, RunReport


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def render_json(report: RunReport) -> str:
    return json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
        default=_json_default,
    ) + "\n"


def _dataset_lines(dataset: DatasetReport, markdown: bool) -> list[str]:
    source = dataset.source
    heading = f"Dataset: {source.get('file_name', 'unknown')}"
    lines = [f"## {heading}" if markdown else heading]
    lines.append(f"Status: {dataset.status.value}")
    if dataset.status.value == "error":
        for error in dataset.errors:
            lines.append(f"Error: {error.get('message', 'analysis failed')}")
        return lines

    facts = dataset.observed_facts
    lines.extend(
        [
            f"Format: {source.get('detected_format')}",
            f"Rows: {facts.get('row_count')} (analyzed: {facts.get('analyzed_row_count')})",
            f"Columns: {facts.get('column_count')}",
            f"Column names: {', '.join(facts.get('column_names', []))}",
            f"Summary: {dataset.inferences.get('plain_language_summary', '')}",
        ]
    )
    columns = facts.get("columns", [])
    if columns:
        lines.append("Columns:")
        for column in columns:
            lines.append(
                f"- {column['name']}: {column['inferred_type']}; "
                f"missing={column['missing_count']} ({column['missing_percentage']:.2f}%)"
            )
    issues = dataset.inferences.get("data_quality_issues", [])
    if issues:
        lines.append("Potential data-quality issues:")
        for issue in issues:
            detail = issue.get("column") or issue.get("columns") or issue.get("observed_count", "")
            lines.append(f"- {issue['code']}: {detail}")
    if dataset.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in dataset.warnings)
    if dataset.skipped_analyses:
        lines.append("Skipped analyses:")
        lines.extend(
            f"- {item['analysis']}: {item['reason']}" for item in dataset.skipped_analyses
        )
    return lines


def render_text(report: RunReport) -> str:
    lines = [
        "GE-108 Data Analyzer",
        f"Run status: {report.status}",
        f"Successful datasets: {report.successful_count}",
        f"Failed datasets: {report.failed_count}",
        "",
    ]
    for dataset in report.datasets:
        lines.extend(_dataset_lines(dataset, markdown=False))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_markdown(report: RunReport) -> str:
    lines = [
        "# GE-108 Data Analysis Report",
        "",
        f"- Run status: `{report.status}`",
        f"- Successful datasets: {report.successful_count}",
        f"- Failed datasets: {report.failed_count}",
        "",
    ]
    for dataset in report.datasets:
        lines.extend(_dataset_lines(dataset, markdown=True))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render(report: RunReport, report_format: ReportFormat) -> str:
    if report_format == ReportFormat.JSON:
        return render_json(report)
    if report_format == ReportFormat.MARKDOWN:
        return render_markdown(report)
    return render_text(report)


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return stem[:80] or "dataset"


def output_filename(dataset: DatasetReport, report_format: ReportFormat) -> str:
    source = dataset.source
    stem = _safe_stem(Path(source.get("file_name", "dataset")).stem)
    sheet = source.get("sheet")
    if sheet:
        stem += f"--sheet-{_safe_stem(str(sheet))}"
    extension = {
        ReportFormat.JSON: ".json",
        ReportFormat.MARKDOWN: ".md",
        ReportFormat.TEXT: ".txt",
    }[report_format]
    return f"{stem}--{source.get('source_id', 'unknown')}{extension}"


def _ensure_output_dir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise OutputError(f'could not create output directory: "{path}"') from exc
    if not resolved.is_dir():
        raise OutputError(f'output path is not a directory: "{path}"')
    if not os.access(resolved, os.W_OK):
        raise OutputError(f'output directory is not writable: "{path}"')
    return resolved


def atomic_write(path: Path, content: str, overwrite: bool) -> None:
    if not overwrite:
        descriptor: int | None = None
        created = False
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                descriptor = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            return
        except FileExistsError as exc:
            raise OutputError(
                f'output already exists: "{path}"; use --overwrite to replace generated reports'
            ) from exc
        except OSError as exc:
            if created:
                path.unlink(missing_ok=True)
            raise OutputError(f'could not write output: "{path}"') from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
    temporary: Path | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temp_name)
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OutputError:
        raise
    except OSError as exc:
        raise OutputError(f'could not write output: "{path}"') from exc
    finally:
        if temporary and temporary.exists():
            temporary.unlink(missing_ok=True)


def write_reports(report: RunReport, config: AnalysisConfig) -> list[Path]:
    if config.output is None:
        return []
    output_dir = _ensure_output_dir(config.output)
    extension = {
        ReportFormat.JSON: ".json",
        ReportFormat.MARKDOWN: ".md",
        ReportFormat.TEXT: ".txt",
    }[config.report_format]
    summary_path = output_dir / f"run-summary{extension}"
    paths = [
        output_dir / output_filename(dataset, config.report_format)
        for dataset in report.datasets
    ]
    paths.append(summary_path)
    duplicates = {path for path in paths if paths.count(path) > 1}
    if duplicates:
        raise OutputError(f'generated output filename collision: "{sorted(duplicates)[0]}"')
    if not config.overwrite:
        existing = [path for path in paths if path.exists()]
        if existing:
            raise OutputError(
                f'output already exists: "{existing[0]}"; use --overwrite to replace generated reports'
            )
    for dataset, path in zip(report.datasets, paths):
        atomic_write(path, render(RunReport([dataset]), config.report_format), config.overwrite)
    atomic_write(summary_path, render(report, config.report_format), config.overwrite)
    report.output_paths = [str(path) for path in paths]
    return paths
