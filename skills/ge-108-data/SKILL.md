---
name: ge-108-data
description: Analyze local GE-108 .data.zip/.data.ok production files and profile CSV, TSV, JSON, JSONL, Excel, or Parquet datasets safely. Use for GE-108 sent-folder duplicate stringCode analysis, missing values, summaries, outliers, schema comparisons, or data-quality reports.
license: MIT
compatibility: Requires Python 3.11+ and dependencies from requirements.txt; processes data locally without network access.
metadata:
  version: "0.2.0"
---

# GE-108 Data Analyzer

Analyze GE-108 sent archives and profile local tabular data without changing source files or transmitting data.

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
- Analyze GE-108 data in `data/products/sent` for a specific date.
- Find duplicate `stringCode` values across GE-108 `.data.ok` files.

Do not use it for unrelated programming, destructive cleanup, database administration without an authorized local export, or remote extraction without established access and authorization.

## Workflow

1. Before asking for input, inspect the request, attachments, inline data, referenced paths, files already in the workspace, and relevant prior conversation.
2. If no usable source exists, ask exactly: “Please provide the file or folder path containing the data to analyze, or paste the data directly.” Do not ask this when data is already available.
3. Validate the selected inputs. If a path is missing, inaccessible, or ambiguous, state the exact path checked, explain the problem, ask for a corrected or accessible path, and never invent an alternative.
4. Infer the requested analysis objective. Use the default profile when the user asks broadly.
5. Install local dependencies if needed: `python3 -m pip install -r requirements.txt` from this skill directory.
6. For a GE-108 `data/products/sent` directory, identify the requested date and run the dedicated `--sent-dir`/`--date` mode. For tabular input, use `--input`.
7. Run `date_executor.py` with the minimum necessary flags. Quote every path.
8. Check the process exit status. Exit `0` is success; `10` means only some tabular inputs succeeded. Other nonzero statuses are failures documented by `--help` and the error output.
9. Validate duplicate counts, production counts, report paths, row counts, inferred types, warnings, sampling notices, and skipped analyses as applicable.
10. Never fabricate findings, output paths, or execution results. Do not claim a failed input was analyzed.
11. Summarize the strongest observed findings, clearly distinguish inferences, and list persisted report paths.
12. Protect confidential and personal information. Do not expose complete records or unmasked sensitive values beyond duplicate codes explicitly required by the GE-108 report.
13. Ask one focused follow-up only when analysis cannot proceed safely.

## Commands

From the skill directory:

```bash
python3 date_executor.py --input "/path/to/data.csv"
python3 date_executor.py --input "/path/to/folder" --recursive --format markdown --output "/path/to/reports"
python3 date_executor.py --input "/path/to/book.xlsx" --sheet "Summary"
python3 date_executor.py --input "/path/to/one.csv" --input "/path/to/two.parquet" --format json
python3 date_executor.py --sent-dir "/path/to/data/products/sent" --date "25/06/2026"
```

For inline CSV, TSV, JSON, or JSONL, pipe content through standard input rather than placing confidential data in command arguments:

```bash
python3 date_executor.py --input - --format json < "/path/to/data.jsonl"
```

Run `python3 date_executor.py --help` for the complete interface.

## Safety Rules

- The script does not upload data, call remote services, send telemetry, delete inputs, or modify source files.
- GE-108 mode copies matching root-level files into `<sent-dir>/DD-MM-YYYY`, safely extracts `.data.zip` archives under `OKFILe`, scans `.data.ok` files, and writes four duplicate reports there.
- GE-108 mode rejects ZIP traversal paths, archive symlinks, excessive member counts, excessive expanded size, and extreme compression ratios.
- Tabular reports are persisted only when `--output` is supplied. GE-108 mode always writes its four reports under the generated date directory's `OKFILe` folder.
- Sensitive-column detection is heuristic and can miss or over-classify data. Masking protects displayed values but is not a compliance certification.
- Sampling and skipped analyses are reported explicitly. Do not present estimates as exact observations.
- Outlier indicators are not proof of invalid data.
- Schema compatibility does not authorize combining datasets. Version 1 analyzes files independently.
- Correlation must never be described as causation.

For machine-readable field semantics, read [references/report-schema.md](references/report-schema.md).
