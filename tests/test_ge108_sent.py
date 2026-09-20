from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from ge108_data.ge108_sent import (
    analysis_output_dir,
    extract_date,
    normalize_base_dir,
    prompt_for_valid_date,
    run,
)


def data_ok(codes: list[tuple[str, str, str, str]]) -> str:
    lines = ["<Product-array>"]
    for code, encoder, sequence, status in codes:
        lines.extend(
            [
                '  <Product activationDate="2026-06-25 00:00:00 UTC">',
                f'    <code stringCode="{code}" encoderId="{encoder}" sequence="{sequence}">',
                f'    <status description="{status}"/>',
                "  </Product>",
            ]
        )
    lines.append("</Product-array>")
    return "\n".join(lines)


def test_full_workflow_matches_repository_script(tmp_path: Path, capsys):
    ge108 = tmp_path / "GE-108-data"
    sent = ge108 / "data" / "products" / "sent"
    sent.mkdir(parents=True)
    archive = sent / "2026-06-25--08-00-00.data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(
            "first.data.ok",
            data_ok([("duplicate", "10", "1", "GOOD"), ("unique", "10", "2", "GOOD")]),
        )
        output.writestr(
            "second.data.ok",
            data_ok([("duplicate", "11", "3", "BAD")]),
        )

    okfile = run("analyze 25/06/2026", sent)
    output = capsys.readouterr().out

    assert okfile == sent / "25-06-2026" / "OKFILe"
    assert (sent / "25-06-2026" / archive.name).is_file()
    assert (okfile / "first.data.ok").is_file()
    assert "Copied 1 .data.zip file(s)" in output
    assert "Moved 2 extracted path(s)" in output
    assert "Total production count: 3" in output
    assert "Duplicate groups found: 1" in output
    assert "Total duplicate occurrences: 2" in output
    assert "Groups with mixed statuses: 1" in output
    assert "Top status:" in output
    assert "Top status combination:" in output
    assert "Top file:" in output

    detail = (ge108 / "duplicate_report.txt").read_text(encoding="utf-8")
    status = (ge108 / "duplicate_status_report.txt").read_text(encoding="utf-8")
    summary = (ge108 / "duplicate_status_summary.txt").read_text(encoding="utf-8")
    assert "DUPLICATE CODE: duplicate" in detail
    assert "unique" not in detail
    assert "⚠ Appears in MULTIPLE FILES" in detail
    assert "Status: GOOD" in status
    assert "Status: BAD" in status
    assert "Sample duplicate groups:" in summary


def test_existing_workspace_is_reused_and_overwritten_like_source(tmp_path: Path):
    ge108 = tmp_path / "GE-108-data"
    sent = ge108 / "data" / "products" / "sent"
    sent.mkdir(parents=True)
    source = sent / "2026-06-25--one.data.ok"
    source.write_text(data_ok([("first", "1", "1", "GOOD")]), encoding="utf-8")
    run("25/06/2026", sent)
    source.write_text(data_ok([("second", "2", "2", "BAD")]), encoding="utf-8")
    run("25/06/2026", sent)
    copied = sent / "25-06-2026" / "OKFILe" / source.name
    assert "second" in copied.read_text(encoding="utf-8")


def test_zip_traversal_is_rejected(tmp_path: Path):
    sent = tmp_path / "data" / "products" / "sent"
    sent.mkdir(parents=True)
    with zipfile.ZipFile(sent / "2026-06-25--unsafe.data.zip", "w") as archive:
        archive.writestr("../escaped.data.ok", "unsafe")
    with pytest.raises(ValueError, match="unsafe path"):
        run("25/06/2026", sent)
    assert not (sent / "escaped.data.ok").exists()


def test_late_invalid_zip_member_leaves_no_partial_extraction(tmp_path: Path):
    sent = tmp_path / "data" / "products" / "sent"
    sent.mkdir(parents=True)
    with zipfile.ZipFile(sent / "2026-06-25--unsafe.data.zip", "w") as archive:
        archive.writestr("valid.data.ok", "would be partial")
        archive.writestr("../escaped.data.ok", "unsafe")
    with pytest.raises(ValueError, match="unsafe path"):
        run("25/06/2026", sent)
    date_dir = sent / "25-06-2026"
    assert not (date_dir / "valid.data.ok").exists()
    assert not (date_dir / "OKFILe" / "valid.data.ok").exists()


def test_symlinked_generated_workspace_is_rejected(tmp_path: Path):
    sent = tmp_path / "data" / "products" / "sent"
    sent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (sent / "25-06-2026").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic link"):
        run("25/06/2026", sent)


def test_date_prompt_and_path_normalization(tmp_path: Path, monkeypatch, capsys):
    sent = tmp_path / "data" / "products" / "sent"
    sent.mkdir(parents=True)
    assert normalize_base_dir(tmp_path) == sent
    assert analysis_output_dir(sent) == tmp_path
    assert extract_date("analyze 25-06-2026") == "25/06/2026"
    answers = iter(["bad", "25/06/2026"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    parsed, provided = prompt_for_valid_date(None)
    assert parsed.strftime("%Y-%m-%d") == "2026-06-25"
    assert provided == "25/06/2026"
    assert "No date found" in capsys.readouterr().out
