---
name: ge-108-data
description: Analyze GE-108 production archives in data/products/sent for duplicate stringCode values. Use when the user asks to analyze GE-108-data, inspect .data.zip or .data.ok files, process a production date, or generate duplicate and status reports.
license: MIT
compatibility: Requires Python 3.10+; uses only the standard library and processes data locally without network access.
metadata:
  version: "1.0.0"
---

# GE-108 Data Analyzer

Use this skill only for the GE-108 `data/products/sent` archive workflow. Do not use generic tabular profiling or `--input`.

## Workflow

1. Inspect the request, prior conversation, and workspace before asking questions.
2. Locate the GE-108 sent directory. Prefer `src/main/java/GE-108-data/data/products/sent` when it exists. Otherwise use an explicitly supplied `data/products/sent` path. Never invent a path.
3. Identify the requested date in `DD/MM/YYYY` or `DD-MM-YYYY` format.
4. If no valid date is available, ask exactly: “Which date should I analyze? Please provide it in DD/MM/YYYY format.”
5. Tell the user that the workflow creates or updates `<sent-dir>/DD-MM-YYYY/OKFILe` and overwrites the four duplicate reports beside the GE-108 `data` directory's parent, matching the repository script.
6. Run the installed `date_executor.py` with `--sent-dir` and a positional date query:

```bash
python3 date_executor.py --sent-dir "/path/to/data/products/sent" "25/06/2026"
```

7. Check the process exit status. Do not claim analysis succeeded unless it exits with `0`.
8. Report the copied archive count, extracted path count, total production count, duplicate groups, duplicate occurrences, same/mixed-status counts, top status, top status combination, top file, and all report paths.

## Script Behavior

For the selected date, the script:

- Creates or reuses `<sent-dir>/DD-MM-YYYY/OKFILe`.
- Copies root-level files beginning with `YYYY-MM-DD`.
- Keeps copied `.data.zip` files in the date directory.
- Safely extracts archives and moves extracted content into `OKFILe`.
- Recursively scans `.data.ok` files for duplicate `stringCode` values.
- Captures file, product index, sequence, encoder, and inherited status.
- Writes `duplicate_report.txt`, `duplicate_count_report.txt`, `duplicate_status_report.txt`, and `duplicate_status_summary.txt` at the GE-108 project directory inferred from `data/products/sent`.

## Safety

- Processing is local and makes no network calls.
- Source files in the root sent directory are copied, not modified or deleted.
- ZIP traversal paths, archive symlinks, excessive member counts, excessive expanded size, extreme compression ratios, and symlinked generated workspaces are rejected. These are intentional safety hardening beyond the repository script.
- The generated date workspace and reports intentionally follow the source script's overwrite behavior.
- Duplicate codes are operational report data; avoid reproducing unnecessary full records in chat.
