from __future__ import annotations

import sys
from pathlib import Path


def test_cli_runs_non_interactively(cli_module, tmp_path: Path, monkeypatch, capsys):
    sent = tmp_path / "data" / "products" / "sent"
    sent.mkdir(parents=True)
    (sent / "2026-06-25--one.data.ok").write_text(
        '<Product><code stringCode="x" encoderId="1" sequence="1"><status description="GOOD"/></Product>\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["date_executor.py", "--sent-dir", str(sent), "25/06/2026"],
    )
    assert cli_module.main() == 0
    output = capsys.readouterr().out
    assert "Created or verified date directory" in output
    assert "Total production count: 0" in output
    assert "Duplicate groups found: 0" in output


def test_cli_prompts_for_date_when_query_missing(cli_module, tmp_path: Path, monkeypatch):
    sent = tmp_path / "sent"
    sent.mkdir()
    (sent / "2026-06-25--one.data.ok").write_text("<Product />\n", encoding="utf-8")
    answers = iter(["25/06/2026"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(sys, "argv", ["date_executor.py", "--sent-dir", str(sent)])
    assert cli_module.main() == 0


def test_cli_discovers_loganalyzer_workspace(cli_module, tmp_path: Path, monkeypatch):
    sent = tmp_path / "src" / "main" / "java" / "GE-108-data" / "data" / "products" / "sent"
    sent.mkdir(parents=True)
    (sent / "2026-06-25--one.data.ok").write_text("<Product />\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["date_executor.py", "25/06/2026"])
    assert cli_module.main() == 0
    assert (sent / "25-06-2026" / "OKFILe").is_dir()


def test_skill_is_archive_only():
    skill = Path(__file__).resolve().parents[1] / "skills" / "ge-108-data" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\nname: ge-108-data\n")
    assert "Do not use generic tabular profiling or `--input`" in text
