---
name: ge-108-data
description: Analyze and profile local CSV, TSV, JSON, JSONL, Excel, and Parquet datasets safely. Use when asked to inspect a dataset or folder, summarize tabular data, find missing values or duplicates, detect outliers, compare schemas, or generate a local data-quality report.
license: MIT
compatibility: Requires Python 3.11+ and dependencies from requirements.txt; processes data locally without network access.
metadata:
  version: "0.1.0"
---

# GE-108 Data Analyzer

Profile local tabular data without changing source files or transmitting data.

## When To Use

Use this skill for requests such as:

- Analyze this dataset.
- Profile this CSV.
- Find missing values.
- Summarize this Excel workbook.
- Compare these datasets or their schemas.
- Detect duplicates or outliers.
- Generate a data-quality report.
- Analyze supported files in this folder.

Do not use it for unrelated programming, destructive cleanup, database administration without an authorized local export, or remote extraction without established access and authorization.

## Workflow

1. Before asking for input, inspect the request, attachments, inline data, referenced paths, files already in the workspace, and relevant prior conversation.
2. If no usable source exists, ask exactly: “Please provide the file or folder path containing the data to analyze, or paste the data directly.” Do not ask this when data is already available.
3. Validate the selected inputs. If a path is missing, inaccessible, or ambiguous, state the exact path checked, explain the problem, ask for a corrected or accessible path, and never invent an alternative.
4. Infer the requested analysis objective. Use the default profile when the user asks broadly.
5. Install local dependencies if needed: `python3 -m pip install -r requirements.txt` from this skill directory.
6. Run `date_executor.py` with the minimum necessary flags. Quote every path.
7. Check the process exit status. Exit `0` is success; `10` means only some inputs succeeded. Other nonzero statuses are failures documented by `--help` and the error output.
8. Validate row counts, inferred column types, missing values, warnings, sampling notices, and skipped analyses before summarizing.
9. Never fabricate findings, output paths, or execution results. Do not claim a failed input was analyzed.
10. Summarize the strongest observed findings, clearly distinguish inferences, and list persisted report paths.
11. Protect confidential and personal information. Do not expose complete records or unmasked sensitive values.
12. Ask one focused follow-up only when analysis cannot proceed safely.

## Commands

From the skill directory:

```bash
python3 date_executor.py --input "/path/to/data.csv"
python3 date_executor.py --input "/path/to/folder" --recursive --format markdown --output "/path/to/reports"
python3 date_executor.py --input "/path/to/book.xlsx" --sheet "Summary"
python3 date_executor.py --input "/path/to/one.csv" --input "/path/to/two.parquet" --format json
```

For inline CSV, TSV, JSON, or JSONL, pipe content through standard input rather than placing confidential data in command arguments:

```bash
python3 date_executor.py --input - --format json < "/path/to/data.jsonl"
```

Run `python3 date_executor.py --help` for the complete interface.

## Safety Rules

- The script does not upload data, call remote services, send telemetry, delete inputs, or modify source files.
- Reports are written only when `--output` is supplied and never overwrite existing reports unless `--overwrite` is supplied.
- Sensitive-column detection is heuristic and can miss or over-classify data. Masking protects displayed values but is not a compliance certification.
- Sampling and skipped analyses are reported explicitly. Do not present estimates as exact observations.
- Outlier indicators are not proof of invalid data.
- Schema compatibility does not authorize combining datasets. Version 1 analyzes files independently.
- Correlation must never be described as causation.

For machine-readable field semantics, read [references/report-schema.md](references/report-schema.md).
