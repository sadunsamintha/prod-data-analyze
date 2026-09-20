"""Pure and bounded dataset profiling routines."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from .models import AnalysisConfig, DatasetReport, DatasetStatus, LoadedDataset
from .privacy import SensitivityAssessment, classify_sensitive_column, mask_value

DATE_NAME_RE = re.compile(r"(?:^|[_\s-])(date|time|timestamp|created|updated|at)(?:$|[_\s-])", re.I)
ID_NAME_RE = re.compile(r"(?:^|[_\s-])(id|key|uuid|code|number|no)(?:$|[_\s-])", re.I)
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+\-Z]+)?$")
NEAR_CONSTANT_THRESHOLD = 0.95
IDENTIFIER_UNIQUENESS_THRESHOLD = 0.98


def _python_scalar(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def infer_datetime(series: pd.Series, name: str) -> tuple[pd.Series | None, float, str | None]:
    non_null = series.dropna()
    if ptypes.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce", utc=True), 1.0, "native datetime dtype"
    if not (ptypes.is_string_dtype(series) or ptypes.is_object_dtype(series)):
        return None, 0.0, None
    sample = non_null.astype(str).head(500)
    if sample.empty:
        return None, 0.0, None
    pattern_ratio = float(sample.str.match(ISO_DATE_RE).mean())
    if not DATE_NAME_RE.search(str(name)) and pattern_ratio < 0.9:
        return None, 0.0, None
    parsed = pd.to_datetime(sample, errors="coerce", utc=True)
    ratio = float(parsed.notna().mean())
    minimum_ok = len(sample) >= 20 or (DATE_NAME_RE.search(str(name)) and ratio == 1.0)
    if ratio < 0.9 or not minimum_ok:
        return None, ratio, None
    full = pd.to_datetime(series, errors="coerce", utc=True)
    return full, ratio, "conservative ISO/name-assisted parsing"


def infer_logical_type(series: pd.Series, name: str) -> tuple[str, float, str]:
    if ptypes.is_bool_dtype(series):
        return "boolean", 1.0, "native dtype"
    if ptypes.is_integer_dtype(series):
        return "integer", 1.0, "native dtype"
    if ptypes.is_float_dtype(series):
        return "number", 1.0, "native dtype"
    if ptypes.is_datetime64_any_dtype(series):
        return "datetime", 1.0, "native dtype"
    parsed, confidence, evidence = infer_datetime(series, name)
    if parsed is not None:
        return "datetime", confidence, evidence or "parsed values"
    if ptypes.is_string_dtype(series) or ptypes.is_object_dtype(series):
        return "string", 0.9, "string/object dtype"
    return "unknown", 0.5, str(series.dtype)


def numeric_summary(series: pd.Series, method: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    values = pd.to_numeric(series, errors="coerce")
    finite = values[np.isfinite(values)]
    summary: dict[str, Any] = {
        "count": int(values.notna().sum()),
        "finite_count": int(len(finite)),
        "non_finite_count": int(values.notna().sum() - len(finite)),
        "zero_count": int((finite == 0).sum()),
        "negative_count": int((finite < 0).sum()),
    }
    if finite.empty:
        return summary, None
    stats = finite.describe(percentiles=[0.25, 0.5, 0.75])
    summary.update(
        {
            "mean": _python_scalar(stats.get("mean")),
            "std": _python_scalar(stats.get("std")),
            "min": _python_scalar(stats.get("min")),
            "q1": _python_scalar(stats.get("25%")),
            "median": _python_scalar(stats.get("50%")),
            "q3": _python_scalar(stats.get("75%")),
            "max": _python_scalar(stats.get("max")),
        }
    )
    if method == "none" or len(finite) < 4:
        return summary, None
    if method == "iqr":
        q1, q3 = finite.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr == 0:
            return summary, {"method": "iqr", "skipped": "IQR is zero"}
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        count = int(((finite < lower) | (finite > upper)).sum())
        return summary, {
            "method": "iqr",
            "count": count,
            "percentage": count * 100.0 / len(finite),
            "lower_bound": _python_scalar(lower),
            "upper_bound": _python_scalar(upper),
        }
    std = finite.std(ddof=1)
    if std == 0 or pd.isna(std):
        return summary, {"method": "zscore", "skipped": "standard deviation is zero"}
    count = int((((finite - finite.mean()) / std).abs() > 3).sum())
    return summary, {
        "method": "zscore",
        "count": count,
        "percentage": count * 100.0 / len(finite),
    }


def categorical_summary(
    series: pd.Series,
    assessment: SensitivityAssessment,
    limit: int,
    mask_salt: str = "",
) -> dict[str, Any]:
    non_null = series.dropna()
    raw_counts = Counter(str(value) for value in non_null)
    ordered = sorted(raw_counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    values = [
        {
            "value": mask_value(value, assessment, mask_salt),
            "count": count,
            "percentage": count * 100.0 / len(non_null) if len(non_null) else 0.0,
        }
        for value, count in ordered[:limit]
    ]
    return {
        "non_null_count": int(len(non_null)),
        "distinct_count": int(len(raw_counts)),
        "cardinality_ratio": len(raw_counts) / len(non_null) if len(non_null) else 0.0,
        "top_values": values,
        "truncated": len(ordered) > limit,
    }


def profile_dataset(dataset: LoadedDataset, config: AnalysisConfig) -> DatasetReport:
    frame = dataset.frame
    sampled_rows = len(frame)
    total_rows = dataset.total_rows if dataset.total_rows is not None else sampled_rows
    column_profiles: list[dict[str, Any]] = []
    constants: list[str] = []
    near_constants: list[str] = []
    identifiers: list[dict[str, Any]] = []
    numeric: dict[str, Any] = {}
    categorical: dict[str, Any] = {}
    dates: dict[str, Any] = {}
    outliers: dict[str, Any] = {}
    sensitive: list[dict[str, Any]] = []
    quality_issues: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    duplicate_columns = [str(name) for name, count in Counter(map(str, frame.columns)).items() if count > 1]
    if duplicate_columns:
        quality_issues.append(
            {"severity": "warning", "code": "duplicate_columns", "columns": duplicate_columns}
        )

    for column in frame.columns:
        name = str(column)
        series = frame[column]
        if isinstance(series, pd.DataFrame):
            continue
        missing = int(series.isna().sum())
        non_null = series.dropna()
        try:
            distinct = int(non_null.nunique(dropna=True))
        except TypeError:
            distinct = int(non_null.map(lambda value: repr(value)).nunique(dropna=True))
        logical_type, confidence, evidence = infer_logical_type(series, name)
        assessment = classify_sensitive_column(name, series)
        column_profiles.append(
            {
                "name": name,
                "observed_dtype": str(series.dtype),
                "inferred_type": logical_type,
                "inference_confidence": confidence,
                "inference_evidence": evidence,
                "missing_count": missing,
                "missing_percentage": missing * 100.0 / sampled_rows if sampled_rows else 0.0,
                "distinct_non_null_count": distinct,
            }
        )
        if assessment.sensitive:
            sensitive.append(
                {
                    "column": name,
                    "kind": assessment.kind,
                    "confidence": assessment.confidence,
                    "reason": assessment.reason,
                }
            )
        if distinct <= 1:
            constants.append(name)
        elif len(non_null) >= 20:
            dominant_ratio = float(non_null.astype(str).value_counts(normalize=True).iloc[0])
            if dominant_ratio >= NEAR_CONSTANT_THRESHOLD:
                near_constants.append(name)
        uniqueness = distinct / len(non_null) if len(non_null) else 0.0
        if (
            len(non_null) >= 20
            and uniqueness >= IDENTIFIER_UNIQUENESS_THRESHOLD
            and missing / sampled_rows <= 0.02
            and logical_type not in {"number", "datetime"}
        ):
            values = non_null.astype(str).head(100)
            pattern_hint = bool(ID_NAME_RE.search(name)) or bool(values.map(lambda value: bool(UUID_RE.match(value))).mean() >= 0.9)
            if pattern_hint:
                identifiers.append(
                    {"column": name, "uniqueness_ratio": uniqueness, "reason": "high uniqueness and identifier-like name or values"}
                )
        if logical_type in {"integer", "number"} and assessment.sensitive:
            skipped.append(
                {
                    "analysis": f"numeric summary for {name}",
                    "reason": "column is potentially sensitive",
                }
            )
        elif logical_type in {"integer", "number"}:
            summary, outlier = numeric_summary(series, config.outlier_method.value)
            numeric[name] = summary
            if outlier is not None:
                outliers[name] = outlier
        elif logical_type == "datetime":
            parsed, _, parse_evidence = infer_datetime(series, name)
            if parsed is not None and parsed.notna().any():
                dates[name] = {
                    "min": parsed.min().isoformat(),
                    "max": parsed.max().isoformat(),
                    "parsed_count": int(parsed.notna().sum()),
                    "evidence": parse_evidence,
                }
        else:
            categorical[name] = categorical_summary(
                series, assessment, config.max_category_values, dataset.source_id
            )

        if sampled_rows and missing / sampled_rows >= 0.5:
            quality_issues.append(
                {"severity": "warning", "code": "high_missingness", "column": name, "percentage": missing * 100.0 / sampled_rows}
            )

    duplicate_count = int(frame.duplicated().sum())
    if dataset.sampled:
        duplicate_observation: dict[str, Any] = {
            "count_in_sample": duplicate_count,
            "exact": False,
            "sample_size": sampled_rows,
        }
        skipped.append(
            {"analysis": "exact duplicate-row count", "reason": "input exceeded sample-size limit"}
        )
    else:
        duplicate_observation = {"count": duplicate_count, "exact": True}
    if duplicate_count:
        quality_issues.append(
            {"severity": "warning", "code": "duplicate_rows", "observed_count": duplicate_count, "sampled": dataset.sampled}
        )
    for name in constants:
        quality_issues.append({"severity": "info", "code": "constant_column", "column": name})
    for name in near_constants:
        quality_issues.append({"severity": "info", "code": "near_constant_column", "column": name})
    for item in sensitive:
        quality_issues.append({"severity": "warning", "code": "potential_sensitive_data", "column": item["column"]})
    if config.outlier_method.value == "none":
        skipped.append({"analysis": "outlier indicators", "reason": "disabled by --outlier-method none"})

    summary_parts = [f"{total_rows} row(s) and {len(frame.columns)} column(s)"]
    if duplicate_count:
        summary_parts.append(f"{duplicate_count} duplicate row(s) observed{' in the sample' if dataset.sampled else ''}")
    missing_columns = sum(profile["missing_count"] > 0 for profile in column_profiles)
    if missing_columns:
        summary_parts.append(f"missing values in {missing_columns} column(s)")
    if sensitive:
        summary_parts.append(f"{len(sensitive)} potentially sensitive column(s)")

    return DatasetReport(
        source={
            "supplied_path": dataset.source.supplied,
            "file_name": dataset.source.path.name if dataset.source.path else "stdin",
            "detected_format": dataset.input_format.value,
            "source_id": dataset.source_id,
            "sheet": dataset.sheet,
            "size_bytes": dataset.source_size_bytes,
        },
        status=DatasetStatus.SUCCESS,
        observed_facts={
            "row_count": total_rows,
            "row_count_exact": True,
            "analyzed_row_count": sampled_rows,
            "column_count": len(frame.columns),
            "column_names": [str(column) for column in frame.columns],
            "columns": column_profiles,
            "duplicate_rows": duplicate_observation,
            "numeric_summaries": numeric,
            "categorical_summaries": categorical,
            "date_ranges": dates,
        },
        inferences={
            "constant_columns": constants,
            "near_constant_columns": near_constants,
            "near_constant_threshold": NEAR_CONSTANT_THRESHOLD,
            "potential_identifier_columns": identifiers,
            "outlier_indicators": outliers,
            "potential_sensitive_columns": sensitive,
            "data_quality_issues": quality_issues,
            "plain_language_summary": "; ".join(summary_parts) + ".",
        },
        warnings=list(dataset.warnings),
        assumptions=[
            "Sensitive-column detection is heuristic and may miss or over-classify data.",
            "Outlier indicators do not prove that values are erroneous.",
            "Correlation, when requested in a future version, must not be described as causation.",
        ],
        skipped_analyses=skipped,
    )


def compare_schemas(reports: list[DatasetReport]) -> list[dict[str, Any]]:
    successful = [report for report in reports if report.status == DatasetStatus.SUCCESS]
    comparisons: list[dict[str, Any]] = []
    for index, left in enumerate(successful):
        for right in successful[index + 1 :]:
            left_columns = left.observed_facts.get("columns", [])
            right_columns = right.observed_facts.get("columns", [])
            left_names = [item["name"] for item in left_columns]
            right_names = [item["name"] for item in right_columns]
            left_types = {item["name"]: item["inferred_type"] for item in left_columns}
            right_types = {item["name"]: item["inferred_type"] for item in right_columns}
            common = set(left_names) & set(right_names)
            conflicts = sorted(name for name in common if not _types_compatible(left_types[name], right_types[name]))
            if conflicts:
                compatibility = "type-conflicted"
            elif left_names == right_names:
                compatibility = "exact"
            elif set(left_names) == set(right_names):
                compatibility = "reorder-compatible"
            elif set(left_names) <= set(right_names) or set(right_names) <= set(left_names):
                compatibility = "superset/subset"
            elif common:
                compatibility = "partial-overlap"
            else:
                compatibility = "incompatible"
            comparisons.append(
                {
                    "left_source_id": left.source["source_id"],
                    "right_source_id": right.source["source_id"],
                    "compatibility": compatibility,
                    "missing_from_left": sorted(set(right_names) - set(left_names)),
                    "missing_from_right": sorted(set(left_names) - set(right_names)),
                    "type_conflicts": conflicts,
                    "combined": False,
                }
            )
    return comparisons


def _types_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    return {left, right} <= {"integer", "number"}
