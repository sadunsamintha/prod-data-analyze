"""Shared configuration, report models, and typed failures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any


class InputFormat(str, Enum):
    CSV = "csv"
    TSV = "tsv"
    JSON = "json"
    JSONL = "jsonl"
    EXCEL = "xlsx"
    PARQUET = "parquet"


class ReportFormat(str, Enum):
    TEXT = "text"
    JSON = "json"
    MARKDOWN = "markdown"


class OutlierMethod(str, Enum):
    IQR = "iqr"
    ZSCORE = "zscore"
    NONE = "none"


class DatasetStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class ExitCode(IntEnum):
    SUCCESS = 0
    INVALID_ARGUMENTS = 2
    MISSING_INPUT = 3
    UNREADABLE_INPUT = 4
    UNSUPPORTED_FORMAT = 5
    PARSING_FAILURE = 6
    ANALYSIS_FAILURE = 7
    OUTPUT_FAILURE = 8
    EXPORT_FAILURE = 9
    PARTIAL_SUCCESS = 10


@dataclass(frozen=True)
class AnalysisConfig:
    inputs: tuple[str, ...]
    output: Path | None = None
    report_format: ReportFormat = ReportFormat.TEXT
    recursive: bool = False
    sheet: str | None = None
    delimiter: str | None = None
    encoding: str = "utf-8-sig"
    columns: tuple[str, ...] = ()
    sample_size: int = 100_000
    max_category_values: int = 20
    outlier_method: OutlierMethod = OutlierMethod.IQR
    overwrite: bool = False
    verbose: bool = False


@dataclass(frozen=True)
class InputSource:
    supplied: str
    path: Path | None
    root: Path | None
    is_stdin: bool = False


@dataclass
class LoadedDataset:
    source: InputSource
    frame: Any
    input_format: InputFormat
    source_id: str
    sheet: str | None = None
    total_rows: int | None = None
    sampled: bool = False
    sample_method: str | None = None
    source_size_bytes: int | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class DatasetReport:
    source: dict[str, Any]
    status: DatasetStatus
    observed_facts: dict[str, Any] = field(default_factory=dict)
    inferences: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    skipped_analyses: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


@dataclass
class RunReport:
    datasets: list[DatasetReport]
    schema_version: str = "1.0"
    tool_version: str = "0.1.0"
    output_paths: list[str] = field(default_factory=list)

    @property
    def successful_count(self) -> int:
        return sum(item.status == DatasetStatus.SUCCESS for item in self.datasets)

    @property
    def failed_count(self) -> int:
        return sum(item.status == DatasetStatus.ERROR for item in self.datasets)

    @property
    def status(self) -> str:
        if self.failed_count == 0:
            return "success"
        if self.successful_count:
            return "partial_success"
        return "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool": {"name": "ge-108-data", "version": self.tool_version},
            "run": {
                "status": self.status,
                "input_count": len(self.datasets),
                "successful_count": self.successful_count,
                "failed_count": self.failed_count,
                "sampling_seed": 0,
            },
            "datasets": [dataset.to_dict() for dataset in self.datasets],
            "errors": [error for dataset in self.datasets for error in dataset.errors],
        }


class AnalyzerError(Exception):
    exit_code = ExitCode.ANALYSIS_FAILURE

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


class InvalidArgumentsError(AnalyzerError):
    exit_code = ExitCode.INVALID_ARGUMENTS


class MissingInputError(AnalyzerError):
    exit_code = ExitCode.MISSING_INPUT


class UnreadableInputError(AnalyzerError):
    exit_code = ExitCode.UNREADABLE_INPUT


class UnsupportedFormatError(AnalyzerError):
    exit_code = ExitCode.UNSUPPORTED_FORMAT


class ParseInputError(AnalyzerError):
    exit_code = ExitCode.PARSING_FAILURE


class AnalysisError(AnalyzerError):
    exit_code = ExitCode.ANALYSIS_FAILURE


class OutputError(AnalyzerError):
    exit_code = ExitCode.OUTPUT_FAILURE


class ExportError(AnalyzerError):
    exit_code = ExitCode.EXPORT_FAILURE
