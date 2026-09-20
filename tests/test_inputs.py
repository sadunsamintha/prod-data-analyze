from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ge108_data.inputs import discover_files, load_path, validate_input_argument
from ge108_data.models import (
    AnalysisConfig,
    InputFormat,
    MissingInputError,
    ParseInputError,
    UnreadableInputError,
)


def config(**overrides):
    values = {"inputs": ("unused",)}
    values.update(overrides)
    return AnalysisConfig(**values)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("sample.csv", InputFormat.CSV),
        ("sample.tsv", InputFormat.TSV),
        ("sample.json", InputFormat.JSON),
        ("sample.jsonl", InputFormat.JSONL),
    ],
)
def test_load_text_formats(fixtures_dir: Path, name: str, expected: InputFormat):
    path = fixtures_dir / name
    source = validate_input_argument(str(path), Path.cwd())
    dataset = load_path(path, source, config())
    assert dataset.input_format == expected
    assert dataset.total_rows > 0
    assert len(dataset.frame.columns) > 0


def test_load_excel_first_and_named_sheet(tmp_path: Path):
    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1, 2]}).to_excel(writer, index=False, sheet_name="First")
        pd.DataFrame({"b": [3]}).to_excel(writer, index=False, sheet_name="Second")
    source = validate_input_argument(str(path), Path.cwd())
    first = load_path(path, source, config())
    second = load_path(path, source, config(sheet="Second"))
    assert first.sheet == "First"
    assert first.warnings
    assert second.sheet == "Second"
    assert list(second.frame.columns) == ["b"]


def test_load_parquet(tmp_path: Path):
    path = tmp_path / "sample.parquet"
    pd.DataFrame({"id": [1, 2], "value": [3.0, None]}).to_parquet(path)
    source = validate_input_argument(str(path), Path.cwd())
    dataset = load_path(path, source, config())
    assert dataset.input_format == InputFormat.PARQUET
    assert dataset.total_rows == 2


def test_malformed_json_is_parse_error(fixtures_dir: Path):
    path = fixtures_dir / "malformed.json"
    source = validate_input_argument(str(path), Path.cwd())
    with pytest.raises(ParseInputError):
        load_path(path, source, config())


def test_folder_discovery_respects_recursion_and_ignores_hidden(tmp_path: Path):
    (tmp_path / "top.csv").write_text("a\n1\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "nested.json").write_text('[{"a": 1}]', encoding="utf-8")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.csv").write_text("a\n1\n", encoding="utf-8")
    source = validate_input_argument(str(tmp_path), Path.cwd())
    assert [path.name for path in discover_files(source, recursive=False, output_dir=None)] == ["top.csv"]
    assert [path.name for path in discover_files(source, recursive=True, output_dir=None)] == ["nested.json", "top.csv"]


def test_missing_path_keeps_exact_supplied_path(tmp_path: Path):
    missing = str(tmp_path / "missing data.csv")
    with pytest.raises(MissingInputError) as caught:
        validate_input_argument(missing, Path.cwd())
    assert missing in str(caught.value)


def test_discovery_skips_symlink_outside_root(tmp_path: Path):
    outside = tmp_path.parent / "outside-ge108.csv"
    outside.write_text("a\n1\n", encoding="utf-8")
    link = tmp_path / "linked.csv"
    try:
        link.symlink_to(outside)
        (tmp_path / "safe.csv").write_text("a\n2\n", encoding="utf-8")
        source = validate_input_argument(str(tmp_path), Path.cwd())
        assert [path.name for path in discover_files(source, recursive=True, output_dir=None)] == ["safe.csv"]
    finally:
        outside.unlink(missing_ok=True)


def test_unreadable_file_maps_to_typed_error(monkeypatch, fixtures_dir: Path):
    path = fixtures_dir / "sample.csv"
    source = validate_input_argument(str(path), Path.cwd())

    def deny(*args, **kwargs):
        raise PermissionError("secret row value must not escape")

    monkeypatch.setattr(pd, "read_csv", deny)
    with pytest.raises(UnreadableInputError) as caught:
        load_path(path, source, config())
    assert "secret row value" not in str(caught.value)


def test_selected_columns_reject_unknown_name(fixtures_dir: Path):
    path = fixtures_dir / "sample.csv"
    source = validate_input_argument(str(path), Path.cwd())
    with pytest.raises(Exception, match="unknown column"):
        load_path(path, source, config(columns=("not-present",)))


def test_nested_json_is_rejected_precisely(tmp_path: Path):
    path = tmp_path / "nested.json"
    path.write_text('[{"meta": {"value": 1}}]', encoding="utf-8")
    source = validate_input_argument(str(path), Path.cwd())
    with pytest.raises(ParseInputError, match="nested JSON values"):
        load_path(path, source, config())


def test_legitimate_double_hyphen_json_is_discovered(tmp_path: Path):
    path = tmp_path / "sales--2026.json"
    path.write_text('[{"amount": 1}]', encoding="utf-8")
    source = validate_input_argument(str(tmp_path), Path.cwd())
    assert discover_files(source, recursive=False, output_dir=None) == [path.resolve()]
