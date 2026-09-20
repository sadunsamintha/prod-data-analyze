from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from ge108_data.ge108_sent import analyze_sent_archives, parse_requested_date, resolve_sent_dir
from ge108_data.models import OutputError, ParseInputError


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


def test_full_sent_archive_workflow(tmp_path: Path):
    sent = tmp_path / "data" / "products" / "sent"
    sent.mkdir(parents=True)
    archive = sent / "2026-06-25--08-00-00.data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(
            "first.data.ok",
            data_ok([("duplicate", "10", "1", "GOOD"), ("unique", "10", "2", "GOOD")]),
        )
        output.writestr(
            "nested/second.data.ok",
            data_ok([("duplicate", "11", "3", "BAD")]),
        )
    unrelated = sent / "2026-06-24--08-00-00.data.zip"
    with zipfile.ZipFile(unrelated, "w") as output:
        output.writestr("ignored.data.ok", data_ok([("duplicate", "9", "0", "GOOD")]))

    result = analyze_sent_archives(tmp_path, "25/06/2026")

    assert result.sent_dir == sent
    assert result.date_dir.name == "25-06-2026"
    assert result.scanned_files == 2
    assert result.total_product_count == 3
    assert result.duplicate_code_count == 1
    assert result.duplicate_entry_count == 2
    assert result.mixed_status_groups == 1
    assert archive.read_bytes()
    detail = (result.okfile_dir / "duplicate_report.txt").read_text(encoding="utf-8")
    status = (result.okfile_dir / "duplicate_status_report.txt").read_text(encoding="utf-8")
    assert "DUPLICATE CODE: duplicate" in detail
    assert "unique" not in detail
    assert "Status: GOOD" in status
    assert "Status: BAD" in status


def test_existing_outputs_require_overwrite(tmp_path: Path):
    sent = tmp_path / "sent"
    sent.mkdir()
    archive = sent / "2026-06-25--data.data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("one.data.ok", data_ok([("x", "1", "1", "GOOD")]))
    analyze_sent_archives(sent, "25-06-2026")
    with pytest.raises(OutputError):
        analyze_sent_archives(sent, "25-06-2026")
    result = analyze_sent_archives(sent, "25-06-2026", overwrite=True)
    assert result.scanned_files == 1


def test_overwrite_rebuilds_workspace_without_stale_files(tmp_path: Path):
    sent = tmp_path / "sent"
    sent.mkdir()
    archive = sent / "2026-06-25--data.data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("old.data.ok", data_ok([("old", "1", "1", "GOOD")]))
    first = analyze_sent_archives(sent, "25/06/2026")
    assert (first.okfile_dir / "old.data.ok").exists()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("new.data.ok", data_ok([("new", "1", "1", "GOOD")]))
    second = analyze_sent_archives(sent, "25/06/2026", overwrite=True)
    assert not (second.okfile_dir / "old.data.ok").exists()
    assert (second.okfile_dir / "new.data.ok").exists()


def test_zip_traversal_is_rejected(tmp_path: Path):
    sent = tmp_path / "sent"
    sent.mkdir()
    archive = sent / "2026-06-25--unsafe.data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escaped.data.ok", "unsafe")
    with pytest.raises(ParseInputError, match="unsafe path"):
        analyze_sent_archives(sent, "25/06/2026")
    assert not (tmp_path / "escaped.data.ok").exists()


def test_date_and_sent_directory_normalization(tmp_path: Path):
    sent = tmp_path / "data" / "products" / "sent"
    sent.mkdir(parents=True)
    assert resolve_sent_dir(tmp_path) == sent
    assert parse_requested_date("analyze 25-06-2026").strftime("%Y-%m-%d") == "2026-06-25"


def test_duplicate_report_uses_relative_paths_for_same_basenames(tmp_path: Path):
    sent = tmp_path / "sent"
    sent.mkdir()
    archive = sent / "2026-06-25--data.data.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("a/same.data.ok", data_ok([("duplicate", "1", "1", "GOOD")]))
        output.writestr("b/same.data.ok", data_ok([("duplicate", "2", "2", "GOOD")]))
    result = analyze_sent_archives(sent, "25/06/2026")
    detail = (result.okfile_dir / "duplicate_report.txt").read_text(encoding="utf-8")
    assert "a/same.data.ok" in detail
    assert "b/same.data.ok" in detail
    assert "MULTIPLE FILES" in detail


def test_existing_symlink_workspace_is_rejected(tmp_path: Path):
    sent = tmp_path / "sent"
    sent.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (sent / "25-06-2026").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OutputError, match="unsafe generated date path"):
        analyze_sent_archives(sent, "25/06/2026", overwrite=True)
