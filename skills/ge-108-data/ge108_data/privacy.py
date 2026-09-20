"""Heuristic sensitive-data detection and report-boundary masking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

SENSITIVE_NAME_RE = re.compile(
    r"(?:^|[_\s-])(password|passwd|secret|token|api[_-]?key|access[_-]?key|"
    r"email|e-mail|phone|mobile|ssn|social[_-]?security|passport|credit[_-]?card|"
    r"card[_-]?number|account[_-]?number|address)(?:$|[_\s-])",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9() .-]{7,}[0-9]$")
TOKEN_RE = re.compile(
    r"^(?:sk-|gh[pousr]_|xox[baprs]-|AIza|AKIA)[A-Za-z0-9_\-/.+=]{8,}$"
)
LONG_SECRET_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9_+=-]{24,}$")


@dataclass(frozen=True)
class SensitivityAssessment:
    sensitive: bool
    kind: str | None
    confidence: str
    reason: str | None


def looks_like_sensitive_value(value: Any) -> str | None:
    if value is None or (not isinstance(value, (list, dict, tuple, set)) and pd.isna(value)):
        return None
    text = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$", text):
        return None
    if EMAIL_RE.match(text):
        return "email"
    if TOKEN_RE.match(text) or LONG_SECRET_RE.match(text):
        return "secret"
    digits = re.sub(r"\D", "", text)
    if PHONE_RE.match(text) and 10 <= len(digits) <= 15:
        return "phone"
    return None


def classify_sensitive_column(name: str, series: pd.Series) -> SensitivityAssessment:
    name_match = SENSITIVE_NAME_RE.search(str(name))
    if name_match:
        return SensitivityAssessment(
            True, name_match.group(1).lower(), "high", "column name suggests sensitive data"
        )

    sample = series.dropna().head(100)
    matches = [looks_like_sensitive_value(value) for value in sample]
    matched = [kind for kind in matches if kind]
    if sample.size and len(matched) / sample.size >= 0.5:
        kind = max(set(matched), key=matched.count)
        return SensitivityAssessment(
            True, kind, "medium", "sampled values resemble sensitive data"
        )
    return SensitivityAssessment(False, None, "low", None)


def mask_value(value: Any, assessment: SensitivityAssessment, salt: str = "") -> str:
    if value is None or (not isinstance(value, (list, dict, tuple, set)) and pd.isna(value)):
        return "[missing]"
    value_kind = looks_like_sensitive_value(value)
    if not assessment.sensitive and value_kind is None:
        return sanitize_display_value(value)
    text = str(value)
    kind = value_kind or assessment.kind
    if kind in {"secret", "password", "passwd", "token", "api_key"}:
        return "[masked-secret]"
    digest = hashlib.sha256(
        f"{salt}\0{text}".encode("utf-8", errors="replace")
    ).hexdigest()[:8]
    return f"[masked-{kind or 'sensitive'}-{digest}]"


def sanitize_display_value(value: Any) -> str:
    text = str(value).replace("\x00", "")
    if text.startswith(("=", "+", "@")):
        return "'[formula-like value]"
    if text.startswith("-") and not _is_number(text):
        return "'[formula-like value]"
    return text


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def redact_message(message: str) -> str:
    tokens = re.split(r"(\s+)", message)
    for index, token in enumerate(tokens):
        stripped = token.strip("'\"(),;:")
        kind = looks_like_sensitive_value(stripped)
        if kind:
            tokens[index] = token.replace(stripped, f"[masked-{kind}]")
    return "".join(tokens)
