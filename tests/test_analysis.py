from __future__ import annotations

from pathlib import Path

import pandas as pd

from ge108_data.analysis import compare_schemas, profile_dataset
from ge108_data.models import AnalysisConfig, InputFormat, InputSource, LoadedDataset, OutlierMethod


def make_dataset(frame: pd.DataFrame, *, sampled: bool = False, source_id: str = "source") -> LoadedDataset:
    return LoadedDataset(
        source=InputSource("sample.csv", Path("sample.csv"), Path(".")),
        frame=frame,
        input_format=InputFormat.CSV,
        source_id=source_id,
        total_rows=len(frame) + (10 if sampled else 0),
        sampled=sampled,
    )


def config(**overrides):
    values = {"inputs": ("sample.csv",)}
    values.update(overrides)
    return AnalysisConfig(**values)


def test_profile_required_analyses():
    frame = pd.DataFrame(
        {
            "record_id": [f"ID-{i}" for i in range(20)],
            "amount": list(range(19)) + [1000],
            "category": ["same"] * 19 + ["other"],
            "event_date": pd.date_range("2026-01-01", periods=20),
            "missing": [None] * 10 + ["x"] * 10,
        }
    )
    report = profile_dataset(make_dataset(frame), config())
    assert report.observed_facts["row_count"] == 20
    assert report.observed_facts["numeric_summaries"]["amount"]["max"] == 1000
    assert report.observed_facts["date_ranges"]["event_date"]["min"].startswith("2026-01-01")
    assert "category" in report.inferences["near_constant_columns"]
    assert report.inferences["potential_identifier_columns"][0]["column"] == "record_id"
    assert report.inferences["outlier_indicators"]["amount"]["count"] == 1


def test_empty_and_string_only_dataset_succeeds():
    report = profile_dataset(make_dataset(pd.DataFrame({"label": pd.Series(dtype="object")})), config())
    assert report.observed_facts["row_count"] == 0
    assert report.observed_facts["numeric_summaries"] == {}


def test_sampled_duplicates_are_not_claimed_exact():
    frame = pd.DataFrame({"a": [1, 1]})
    report = profile_dataset(make_dataset(frame, sampled=True), config())
    assert report.observed_facts["duplicate_rows"]["exact"] is False
    assert report.skipped_analyses


def test_outlier_none_is_recorded_as_skipped():
    report = profile_dataset(
        make_dataset(pd.DataFrame({"value": [1, 2, 3]})),
        config(outlier_method=OutlierMethod.NONE),
    )
    assert any(item["analysis"] == "outlier indicators" for item in report.skipped_analyses)


def test_schema_comparison_reports_type_conflict():
    left = profile_dataset(make_dataset(pd.DataFrame({"id": [1]}), source_id="left"), config())
    right = profile_dataset(make_dataset(pd.DataFrame({"id": ["x"]}), source_id="right"), config())
    result = compare_schemas([left, right])
    assert result[0]["compatibility"] == "type-conflicted"
    assert result[0]["combined"] is False


def test_high_cardinality_is_bounded():
    frame = pd.DataFrame({"label": [f"value-{index}" for index in range(100)]})
    report = profile_dataset(make_dataset(frame), config(max_category_values=5))
    summary = report.observed_facts["categorical_summaries"]["label"]
    assert len(summary["top_values"]) == 5
    assert summary["truncated"] is True


def test_sensitive_numeric_summary_is_suppressed():
    frame = pd.DataFrame({"account_number": [1234567890123456, 2234567890123456]})
    report = profile_dataset(make_dataset(frame), config())
    assert "account_number" not in report.observed_facts["numeric_summaries"]
    assert any("account_number" in item["analysis"] for item in report.skipped_analyses)


def test_schema_partial_overlap_is_not_called_subset():
    left = profile_dataset(make_dataset(pd.DataFrame({"a": [1], "b": [2]}), source_id="left"), config())
    right = profile_dataset(make_dataset(pd.DataFrame({"a": [1], "c": [2]}), source_id="right"), config())
    assert compare_schemas([left, right])[0]["compatibility"] == "partial-overlap"
