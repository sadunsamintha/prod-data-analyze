# GE-108 Data Analyzer Skill

`ge-108-data` is an Agent Skill for the GE-108 production archive workflow. It copies date-matched files from `data/products/sent`, extracts `.data.zip` archives into `DD-MM-YYYY/OKFILe`, finds duplicate `stringCode` values in `.data.ok` files, and generates duplicate/status reports.

## Install

```bash
DISABLE_TELEMETRY=1 npx skills@latest add sadunsamintha/prod-data-analyze \
  --skill ge-108-data \
  --agent opencode \
  --copy \
  --yes
```

Restart OpenCode after installation or update.

## Update

```bash
DISABLE_TELEMETRY=1 npx skills@latest update ge-108-data -y
```

## Requirements

- Python 3.10 or later
- No third-party Python packages

## Usage

From the project containing `src/main/java/GE-108-data`:

```bash
python3 .agents/skills/ge-108-data/date_executor.py \
  --sent-dir "src/main/java/GE-108-data/data/products/sent" \
  "25/06/2026"
```

The date must be `DD/MM/YYYY` or `DD-MM-YYYY`. Running without a date prompts interactively:

```bash
python3 .agents/skills/ge-108-data/date_executor.py \
  --sent-dir "src/main/java/GE-108-data/data/products/sent"
```

When launched from the LogAnalyzer repository root, the script can discover `src/main/java/GE-108-data/data/products/sent`, so this also works:

```bash
python3 .agents/skills/ge-108-data/date_executor.py
```

## Outputs

The date workspace is:

```text
<sent-dir>/DD-MM-YYYY/OKFILe
```

Matching `.data.zip` files remain as copies in the date directory. Extracted `.data.ok` files are moved into `OKFILe`.

The four reports are written at the GE-108 project directory inferred from `<GE-108-data>/data/products/sent`:

```text
duplicate_report.txt
duplicate_count_report.txt
duplicate_status_report.txt
duplicate_status_summary.txt
```

The console summary includes production count, duplicate groups and occurrences, same/mixed status groups, top status, top status combination, and top involved file.

## Agent Prompt

```text
Use the ge-108-data skill to analyze GE-108 production archives for 25/06/2026. Use src/main/java/GE-108-data/data/products/sent and report all duplicate summary counts and report paths.
```

If the date is omitted, the skill instructs the agent to ask for it before execution.

## Safety

- Source files in the root sent directory are copied rather than modified.
- Processing is local and performs no network calls or telemetry.
- ZIP traversal, archive symlinks, extreme expansion, and symlinked generated workspaces are rejected as safety hardening beyond the original script.
- Existing generated workspace files and reports follow the original script's overwrite behavior.

## Testing

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
python3 skills/ge-108-data/date_executor.py --help
```

## License

MIT. See `LICENSE`.
