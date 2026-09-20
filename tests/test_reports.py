from __future__ import annotations

import json
from pathlib import Path

import pytest

from ge108_data.models import AnalysisConfig, DatasetReport, DatasetStatus, OutputError, ReportFormat, RunReport
from ge108_data.reports import output_filename, render_json, write_reports


def dataset(source_id: str, file_name: str = "same.csv") -> DatasetReport:
    return DatasetReport(
        source={
            "supplied_path": file_name,
            "file_name": file_name,
            "detected_format": "csv",
            "source_id": source_id,
            "sheet": None,
            "size_bytes": 10,
        },
        status=DatasetStatus.SUCCESS,
        observed_facts={"row_count": 1, "column_count": 1, "column_names": ["a"], "columns": []},
    )


def test_json_is_deterministic_and_versioned():
    report = RunReport([dataset("abc")])
    first = render_json(report)
    second = render_json(report)
    assert first == second
    assert json.loads(first)["schema_version"] == "1.0"


def test_filenames_avoid_same_basename_collision():
    assert output_filename(dataset("abc"), ReportFormat.JSON) != output_filename(dataset("def"), ReportFormat.JSON)


def test_output_write_and_overwrite_protection(tmp_path: Path):
    report = RunReport([dataset("abc")])
    config = AnalysisConfig(inputs=("x",), output=tmp_path, report_format=ReportFormat.JSON)
    paths = write_reports(report, config)
    assert len(paths) == 2
    with pytest.raises(OutputError):
        write_reports(report, config)
    overwrite = AnalysisConfig(
        inputs=("x",), output=tmp_path, report_format=ReportFormat.JSON, overwrite=True
    )
    write_reports(report, overwrite)


def test_output_filename_sanitizes_untrusted_source_name():
    report = dataset("abc", "../../unsafe name.csv")
    name = output_filename(report, ReportFormat.JSON)
    assert ".." not in name
    assert "/" not in name
