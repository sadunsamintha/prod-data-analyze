"""Input validation, safe discovery, format detection, and dataset loading."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, TextIO

import pandas as pd

from .models import (
    AnalysisConfig,
    InputFormat,
    InputSource,
    InvalidArgumentsError,
    LoadedDataset,
    MissingInputError,
    ParseInputError,
    UnreadableInputError,
    UnsupportedFormatError,
)

SUPPORTED_SUFFIXES = {
    ".csv": InputFormat.CSV,
    ".tsv": InputFormat.TSV,
    ".tab": InputFormat.TSV,
    ".json": InputFormat.JSON,
    ".jsonl": InputFormat.JSONL,
    ".ndjson": InputFormat.JSONL,
    ".xlsx": InputFormat.EXCEL,
    ".parquet": InputFormat.PARQUET,
    ".pq": InputFormat.PARQUET,
}
IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    "build",
    "dist",
}
GENERATED_NAMES = {"run-summary.json", "run-summary.md", "run-summary.txt"}
MAX_DISCOVERED_FILES = 10_000
MAX_STDIN_BYTES = 100 * 1024 * 1024
MAX_EXCEL_BYTES = 200 * 1024 * 1024
MAX_JSON_BYTES = 200 * 1024 * 1024
TEXT_CHUNK_ROWS = 25_000


def validate_input_argument(value: str, cwd: Path) -> InputSource:
    if value == "-":
        return InputSource(supplied=value, path=None, root=None, is_stdin=True)

    candidate = Path(value).expanduser()
    checked = candidate if candidate.is_absolute() else cwd / candidate
    try:
        exists = checked.exists()
    except OSError as exc:
        raise UnreadableInputError(
            f'cannot access input path: "{value}"', path=value
        ) from exc
    if not exists:
        raise MissingInputError(
            f'input path does not exist: "{value}"', path=value
        )

    try:
        resolved = checked.resolve(strict=True)
    except OSError as exc:
        raise UnreadableInputError(
            f'cannot resolve input path: "{value}"', path=value
        ) from exc
    if not (resolved.is_file() or resolved.is_dir()):
        raise UnreadableInputError(
            f'input path is not a regular file or directory: "{value}"', path=value
        )
    return InputSource(
        supplied=value,
        path=resolved,
        root=resolved if resolved.is_dir() else resolved.parent,
    )


def _is_generated_report(path: Path) -> bool:
    name = path.name.lower()
    if name in GENERATED_NAMES:
        return True
    return bool(
        path.suffix.lower() in {".json", ".md", ".txt"}
        and re.search(r"--[0-9a-f]{12}$", path.stem)
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def discover_files(
    source: InputSource,
    *,
    recursive: bool,
    output_dir: Path | None,
) -> list[Path]:
    if source.is_stdin or source.path is None:
        return []
    if source.path.is_file():
        if source.path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise UnsupportedFormatError(
                f'unsupported input format: "{source.supplied}"', path=source.supplied
            )
        return [source.path]

    root = source.path
    resolved_output = output_dir.resolve(strict=False) if output_dir else None
    selected: list[Path] = []
    iterator: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
    for candidate in iterator:
        relative = candidate.relative_to(root)
        if any(part.startswith(".") or part in IGNORED_DIRS for part in relative.parts):
            continue
        if candidate.name.startswith("~$"):
            continue
        if candidate.is_symlink():
            continue
        if not candidate.is_file():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if not _is_within(resolved, root):
            continue
        if resolved_output and (resolved == resolved_output or _is_within(resolved, resolved_output)):
            continue
        if candidate.suffix.lower() not in SUPPORTED_SUFFIXES or _is_generated_report(candidate):
            continue
        selected.append(resolved)
        if len(selected) > MAX_DISCOVERED_FILES:
            raise InvalidArgumentsError(
                f"folder contains more than {MAX_DISCOVERED_FILES} supported files; narrow the input"
            )

    selected.sort(key=lambda path: path.relative_to(root).as_posix().casefold())
    if not selected:
        raise MissingInputError(
            f'no supported data files found in: "{source.supplied}"', path=source.supplied
        )
    return selected


def detect_format(path: Path) -> InputFormat:
    try:
        return SUPPORTED_SUFFIXES[path.suffix.lower()]
    except KeyError as exc:
        raise UnsupportedFormatError(
            f'unsupported input format: "{path}"', path=str(path)
        ) from exc


def _source_id(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]


def _sample_frame(frame: pd.DataFrame, limit: int) -> tuple[pd.DataFrame, bool]:
    if len(frame) <= limit:
        return frame.reset_index(drop=True), False
    return frame.sample(n=limit, random_state=0).sort_index().reset_index(drop=True), True


def _read_text_chunks(
    path: Path,
    config: AnalysisConfig,
    delimiter: str,
) -> tuple[pd.DataFrame, int, bool]:
    chunks: list[pd.DataFrame] = []
    retained = 0
    total_rows = 0
    reader = pd.read_csv(
        path,
        sep=delimiter,
        encoding=config.encoding,
        chunksize=TEXT_CHUNK_ROWS,
        low_memory=False,
    )
    for chunk in reader:
        total_rows += len(chunk)
        if retained < config.sample_size:
            take = min(config.sample_size - retained, len(chunk))
            chunks.append(chunk.iloc[:take].copy())
            retained += take
    frame = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    return frame, total_rows, total_rows > retained


def _read_jsonl_chunks(
    path: Path,
    config: AnalysisConfig,
) -> tuple[pd.DataFrame, int, bool]:
    records: list[dict[str, Any]] = []
    total_rows = 0
    with path.open("r", encoding=config.encoding, newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ParseInputError(
                    f"invalid JSON Lines syntax at line {line_number}", path=str(path)
                ) from exc
            if not isinstance(item, dict):
                raise ParseInputError(
                    f"JSON Lines record at line {line_number} is not an object", path=str(path)
                )
            total_rows += 1
            if len(records) < config.sample_size:
                records.append(item)
    return pd.DataFrame.from_records(records), total_rows, total_rows > len(records)


def _json_to_frame(value: Any, path: str) -> pd.DataFrame:
    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            frame = pd.DataFrame.from_records(value)
            _reject_nested_columns(frame, path)
            return frame
        raise ParseInputError("JSON array must contain only objects", path=path)
    if isinstance(value, dict):
        record_keys = [
            key
            for key in ("records", "data", "items")
            if isinstance(value.get(key), list)
            and all(isinstance(item, dict) for item in value[key])
        ]
        if len(record_keys) == 1:
            frame = pd.DataFrame.from_records(value[record_keys[0]])
            _reject_nested_columns(frame, path)
            return frame
        if len(record_keys) > 1:
            raise ParseInputError("JSON contains multiple possible record arrays", path=path)
        list_values = [item for item in value.values() if isinstance(item, list)]
        if list_values and len(list_values) == len(value):
            lengths = {len(item) for item in list_values}
            if len(lengths) == 1:
                return pd.DataFrame(value)
        if all(not isinstance(item, (dict, list)) for item in value.values()):
            return pd.DataFrame([value])
        raise ParseInputError("unsupported or ambiguous nested JSON structure", path=path)
    raise ParseInputError("JSON top level must be an object or array of objects", path=path)


def _reject_nested_columns(frame: pd.DataFrame, path: str) -> None:
    nested = [
        str(column)
        for column in frame.columns
        if frame[column].map(lambda item: isinstance(item, (dict, list))).any()
    ]
    if nested:
        raise ParseInputError(
            f"nested JSON values are not supported in column(s): {', '.join(nested)}",
            path=path,
        )


def _select_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.DataFrame:
    if not columns:
        return frame
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        available = ", ".join(str(column) for column in frame.columns)
        raise InvalidArgumentsError(
            f"unknown column(s): {', '.join(missing)}. Available columns: {available}"
        )
    return frame.loc[:, list(columns)].copy()


def load_path(path: Path, source: InputSource, config: AnalysisConfig) -> LoadedDataset:
    input_format = detect_format(path)
    warnings: list[str] = []
    sheet_name: str | None = None
    try:
        size = path.stat().st_size
        if input_format in {InputFormat.CSV, InputFormat.TSV}:
            delimiter = config.delimiter or ("\t" if input_format == InputFormat.TSV else ",")
            frame, total_rows, sampled = _read_text_chunks(path, config, delimiter)
        elif input_format == InputFormat.JSONL:
            frame, total_rows, sampled = _read_jsonl_chunks(path, config)
        elif input_format == InputFormat.JSON:
            if size > MAX_JSON_BYTES:
                raise ParseInputError(
                    f"JSON input exceeds the {MAX_JSON_BYTES} byte safety limit; convert it to JSONL",
                    path=str(path),
                )
            with path.open("r", encoding=config.encoding) as handle:
                frame = _json_to_frame(json.load(handle), str(path))
            total_rows = len(frame)
            frame, sampled = _sample_frame(frame, config.sample_size)
        elif input_format == InputFormat.EXCEL:
            if size > MAX_EXCEL_BYTES:
                raise ParseInputError(
                    f"Excel input exceeds the {MAX_EXCEL_BYTES} byte safety limit",
                    path=str(path),
                )
            workbook = pd.ExcelFile(path, engine="openpyxl")
            if not workbook.sheet_names:
                raise ParseInputError("Excel workbook contains no worksheets", path=str(path))
            if config.sheet is None:
                selected_sheet: str | int = 0
                sheet_name = workbook.sheet_names[0]
                if len(workbook.sheet_names) > 1:
                    warnings.append(
                        f"Analyzed first worksheet only; skipped {len(workbook.sheet_names) - 1} worksheet(s)."
                    )
            elif config.sheet.isdigit():
                selected_sheet = int(config.sheet)
                if selected_sheet >= len(workbook.sheet_names):
                    raise ParseInputError(
                        f"worksheet index {selected_sheet} is out of range", path=str(path)
                    )
                sheet_name = workbook.sheet_names[selected_sheet]
            else:
                if config.sheet not in workbook.sheet_names:
                    raise ParseInputError(
                        f'worksheet not found: "{config.sheet}"', path=str(path)
                    )
                selected_sheet = config.sheet
                sheet_name = config.sheet
            frame = pd.read_excel(workbook, sheet_name=selected_sheet)
            total_rows = len(frame)
            frame, sampled = _sample_frame(frame, config.sample_size)
        else:
            frame = pd.read_parquet(path, columns=list(config.columns) or None)
            total_rows = len(frame)
            frame, sampled = _sample_frame(frame, config.sample_size)
    except (AnalyzerInputExceptions()) as exc:
        raise exc
    except PermissionError as exc:
        raise UnreadableInputError(f'permission denied reading input: "{source.supplied}"', path=source.supplied) from exc
    except (UnicodeError, csv.Error, json.JSONDecodeError, ValueError, OSError) as exc:
        raise ParseInputError(f'could not parse input: "{source.supplied}"', path=source.supplied) from exc
    except ImportError as exc:
        raise ParseInputError(
            f'missing dependency required to parse: "{source.supplied}"', path=source.supplied
        ) from exc
    except Exception as exc:
        raise ParseInputError(f'could not parse input: "{source.supplied}"', path=source.supplied) from exc

    if input_format != InputFormat.PARQUET:
        frame = _select_columns(frame, config.columns)
    if sampled:
        warnings.append(
            f"Expensive analyses use a deterministic sample of {len(frame)} of {total_rows} rows."
        )
    identity = f"{path.resolve()}#{sheet_name or ''}"
    return LoadedDataset(
        source=InputSource(source.supplied, path, source.root),
        frame=frame,
        input_format=input_format,
        source_id=_source_id(identity),
        sheet=sheet_name,
        total_rows=total_rows,
        sampled=sampled,
        sample_method="first-n streaming sample" if sampled else None,
        source_size_bytes=size,
        warnings=warnings,
    )


def AnalyzerInputExceptions() -> tuple[type[Exception], ...]:
    return (
        InvalidArgumentsError,
        MissingInputError,
        UnreadableInputError,
        UnsupportedFormatError,
        ParseInputError,
    )


def load_stdin(text: str, config: AnalysisConfig) -> LoadedDataset:
    raw = text.encode(config.encoding.replace("-sig", ""), errors="strict")
    if not text.strip():
        raise MissingInputError("standard input is empty", path="-")
    if len(raw) > MAX_STDIN_BYTES:
        raise ParseInputError(
            f"standard input exceeds the {MAX_STDIN_BYTES} byte safety limit", path="-"
        )

    stripped = text.lstrip()
    warnings: list[str] = []
    try:
        if stripped.startswith(("{", "[")):
            try:
                value = json.loads(text)
                frame = _json_to_frame(value, "-")
                input_format = InputFormat.JSON
            except json.JSONDecodeError:
                records = []
                for line_number, line in enumerate(text.splitlines(), 1):
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ParseInputError(
                            f"JSON Lines record at line {line_number} is not an object", path="-"
                        )
                    records.append(item)
                frame = pd.DataFrame.from_records(records)
                input_format = InputFormat.JSONL
        else:
            sample = text[:8192]
            delimiter = config.delimiter
            if delimiter is None:
                try:
                    delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
                except csv.Error as exc:
                    raise UnsupportedFormatError(
                        "could not infer standard-input format; provide a clear delimiter", path="-"
                    ) from exc
            input_format = InputFormat.TSV if delimiter == "\t" else InputFormat.CSV
            frame = pd.read_csv(io.StringIO(text), sep=delimiter)
    except (InvalidArgumentsError, MissingInputError, UnsupportedFormatError, ParseInputError):
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError, csv.Error) as exc:
        raise ParseInputError("could not parse standard input", path="-") from exc

    total_rows = len(frame)
    frame = _select_columns(frame, config.columns)
    frame, sampled = _sample_frame(frame, config.sample_size)
    if sampled:
        warnings.append(
            f"Expensive analyses use a deterministic sample of {len(frame)} of {total_rows} rows."
        )
    return LoadedDataset(
        source=InputSource("-", None, None, is_stdin=True),
        frame=frame,
        input_format=input_format,
        source_id=hashlib.sha256(raw).hexdigest()[:12],
        total_rows=total_rows,
        sampled=sampled,
        sample_method="deterministic random sample" if sampled else None,
        source_size_bytes=len(raw),
        warnings=warnings,
    )
