from __future__ import annotations

import pandas as pd

from ge108_data.analysis import categorical_summary
from ge108_data.privacy import classify_sensitive_column, redact_message, sanitize_display_value


def test_sensitive_values_are_masked_without_changing_counts():
    series = pd.Series(["alice@example.com", "alice@example.com", "bob@example.com"])
    assessment = classify_sensitive_column("email", series)
    summary = categorical_summary(series, assessment, 20)
    assert assessment.sensitive
    assert sum(item["count"] for item in summary["top_values"]) == 3
    assert "alice@example.com" not in str(summary)


def test_formula_like_strings_are_neutralized_but_negative_numbers_are_not():
    assert "formula-like" in sanitize_display_value("=SUM(A1:A2)")
    assert sanitize_display_value("-12.5") == "-12.5"


def test_error_redaction_masks_tokens():
    message = "failed token sk-abcdefghijklmnopqrstuvwxyz"
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in redact_message(message)


def test_iso_dates_are_not_classified_as_phone_numbers():
    assessment = classify_sensitive_column(
        "event_date", pd.Series(["2026-01-01", "2026-01-02"])
    )
    assert assessment.sensitive is False


def test_sparse_secret_is_masked_even_in_non_sensitive_column():
    series = pd.Series(["ordinary", "sk-abcdefghijklmnopqrstuvwxyz", "another"])
    assessment = classify_sensitive_column("notes", series)
    summary = categorical_summary(series, assessment, 20, "source")
    assert assessment.sensitive is False
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in str(summary)
    assert "[masked-secret]" in str(summary)
