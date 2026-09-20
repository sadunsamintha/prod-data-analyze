# GE-108 Data Analyzer Skill

`ge-108-data` is an Agent Skill and local Python CLI for GE-108 production-data duplicate analysis and general tabular profiling. It supports GE-108 `.data.zip`/`.data.ok` workflows plus CSV, TSV, JSON, JSON Lines, Excel `.xlsx`, and Parquet without modifying source files or transmitting data.

## Features

- Shape, columns, inferred types, missingness, and duplicate analysis
- Numeric statistics, categorical frequencies, and datetime ranges
- Constant, near-constant, identifier, outlier, and data-quality indicators
- File, folder, recursive folder, multiple-file, and stdin input
- Text, Markdown, and versioned JSON reports
- Masked report-facing sensitive values and redacted diagnostics
- Deterministic sampling for reasonably large datasets
- Date-based GE-108 sent-archive collection, safe extraction, and duplicate `stringCode` reports

## Prerequisites

- Python 3.11 or later
- Node.js 22.20 or later only when installing through the current `skills` CLI

Create an isolated Python environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r skills/ge-108-data/requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Install From GitHub

```bash
npx skills@latest add sadunsamintha/prod-data-analyze --skill ge-108-data
```

List discoverable skills before installation:

```bash
npx skills@latest add sadunsamintha/prod-data-analyze --list
```

The installer has its own anonymous telemetry policy. Disable installer telemetry with `DISABLE_TELEMETRY=1` or `DO_NOT_TRACK=1`. The Python analyzer itself makes no network or telemetry calls.

## CLI Usage

Repository-relative invocation:

```bash
python skills/ge-108-data/date_executor.py --input <file-or-folder>
```

Equivalent absolute invocation in the requested local checkout:

```bash
python /Users/sadun.samintha/Documents/Tutorials/AI/skills-repo/skills/ge-108-data/date_executor.py --input <file-or-folder>
```

Examples:

```bash
python skills/ge-108-data/date_executor.py --input "data/customers.csv"
python skills/ge-108-data/date_executor.py --input "data" --recursive --format markdown --output "analysis-output"
python skills/ge-108-data/date_executor.py --input "book.xlsx" --sheet "Summary"
python skills/ge-108-data/date_executor.py --input "one.csv" --input "two.parquet" --format json
python skills/ge-108-data/date_executor.py --input - --format json < "events.jsonl"
python skills/ge-108-data/date_executor.py --sent-dir "data/products/sent" --date "25/06/2026"
```

Run `python skills/ge-108-data/date_executor.py --help` for all options.

## GE-108 Sent Data

Use the dedicated mode for a directory containing root-level date-prefixed `.data.zip` or `.data.ok` files:

```bash
python skills/ge-108-data/date_executor.py \
  --sent-dir "src/main/java/GE-108-data/data/products/sent" \
  --date "25/06/2026"
```

The command creates `25-06-2026/OKFILe` under the supplied sent directory, copies files whose names begin with `2026-06-25`, safely extracts matching archives, scans all extracted `.data.ok` files, and writes:

- `duplicate_report.txt`
- `duplicate_count_report.txt`
- `duplicate_status_report.txt`
- `duplicate_status_summary.txt`

Existing copied files or reports are protected. Use `--overwrite` only when replacing a previous generated run is intentional.

## Output

Without `--output`, the report is written to stdout and diagnostics go to stderr. With `--output`, the CLI creates one collision-resistant report per dataset plus `run-summary`, and prints every path it created. Existing reports are protected unless `--overwrite` is supplied.

JSON reports distinguish observed facts, inferences, warnings, assumptions, skipped analyses, and errors. See `skills/ge-108-data/references/report-schema.md`.

## Privacy And Security

- Data remains local; the analyzer has no network integration or telemetry.
- Inputs are opened read-only and are never deleted, renamed, or overwritten.
- GE-108 source archives remain unchanged; only date-specific working copies and reports are created.
- Complete records are not included in standard reports.
- Potential credentials and personal information are masked at report boundaries.
- Sensitive-data detection is heuristic and is not a compliance guarantee.
- Folder traversal ignores hidden files, Git metadata, environments, caches, symlinked directories, and generated reports.
- Large text inputs are chunked and expensive analyses are bounded by `--sample-size`.
- Excel formulas are not evaluated. Formula-like strings are neutralized when displayed.

## Testing

Install development dependencies and run:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
python skills/ge-108-data/date_executor.py --help
```

Tests use synthetic data and require no network, external services, credentials, or confidential datasets.

## Limitations

- Legacy `.xls` is not supported.
- Excel defaults to the first worksheet unless `--sheet` is supplied.
- Files are analyzed independently; schema compatibility does not automatically combine data.
- Filtering, grouping, correlation, time-series aggregation, cleaned-data export, and advanced anomaly detection are deferred.
- Outlier and sensitive-data findings are heuristic.
- The requested executable remains `date_executor.py`; `data_executor.py` may be considered in a future breaking release.

## Publishing

Before publication, confirm the GitHub owner/repository, review `git status` and the staged diff, run the complete tests, push without force, and test discovery and installation from an isolated directory. Do not commit datasets, credentials, virtual environments, caches, or generated reports.

## Contributing

Keep changes local-only, source-preserving, deterministic, and covered by synthetic tests. Avoid adding dependencies unless a required format or safety control justifies them.

## License

MIT. See `LICENSE`.
