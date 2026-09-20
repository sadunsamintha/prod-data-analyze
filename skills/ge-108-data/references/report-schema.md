# Report Schema 1.0

JSON reports use `schema_version: "1.0"`. Additive fields may be introduced within version 1; incompatible changes require a new major version.

## Top Level

- `tool`: Skill name and implementation version.
- `run`: Overall status and successful/failed dataset counts.
- `datasets`: One independent result per selected file or worksheet.
- `errors`: Flattened run-level view of per-dataset errors.

## Dataset Result

- `source`: Supplied path, safe file name, detected format, stable source ID, optional worksheet, and byte size.
- `status`: `success` or `error`.
- `observed_facts`: Values measured directly from parsed data, including shape, columns, missingness, duplicates, and summaries.
- `inferences`: Heuristic types, identifiers, sensitivity, outliers, schema compatibility, and quality issues.
- `warnings`: Conditions reducing completeness or confidence.
- `assumptions`: Defaults and interpretation limits.
- `skipped_analyses`: Analysis not performed and the reason.
- `errors`: Typed, redacted failures for this source.

## Partial Success

When at least one dataset succeeds and another fails, `run.status` is `partial_success` and the process exits with status `10`. Successful results remain valid; failed inputs contain no fabricated analytical facts.

## Value Rules

- Dates use ISO 8601 strings.
- Non-finite numeric values serialize as `null` and remain visible through non-finite counts.
- Sensitive categorical labels are masked while their aggregate counts remain based on original values.
- Sampling uses a fixed seed or deterministic order and is disclosed in warnings.
