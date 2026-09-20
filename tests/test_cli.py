from __future__ import annotations

import io
import json
from pathlib import Path

from ge108_data.models import ExitCode


def run(cli_module, args, stdin_text=""):
    config = cli_module.config_from_args(cli_module.build_parser().parse_args(args))
    stdout = io.StringIO()
    stderr = io.StringIO()
    report, code = cli_module.execute(config, io.StringIO(stdin_text), stdout, stderr)
    return report, code, stdout.getvalue(), stderr.getvalue()


def test_csv_cli_json_output(cli_module, fixtures_dir: Path):
    report, code, stdout, _ = run(
        cli_module,
        ["--input", str(fixtures_dir / "sample.csv"), "--format", "json"],
    )
    assert code == ExitCode.SUCCESS
    assert report.successful_count == 1
    parsed = json.loads(stdout)
    assert parsed["datasets"][0]["observed_facts"]["row_count"] == 4


def test_stdin_jsonl(cli_module):
    _, code, stdout, _ = run(
        cli_module,
        ["--input", "-", "--format", "json"],
        '{"a": 1}\n{"a": 2}\n',
    )
    assert code == ExitCode.SUCCESS
    assert json.loads(stdout)["datasets"][0]["source"]["detected_format"] == "jsonl"


def test_missing_path_returns_specific_code_and_exact_path(cli_module, tmp_path: Path):
    path = str(tmp_path / "missing file.csv")
    _, code, _, stderr = run(cli_module, ["--input", path])
    assert code == ExitCode.MISSING_INPUT
    assert path in stderr
    assert "corrected or accessible path" in stderr


def test_partial_success(cli_module, fixtures_dir: Path):
    _, code, stdout, _ = run(
        cli_module,
        [
            "--input",
            str(fixtures_dir / "sample.csv"),
            "--input",
            str(fixtures_dir / "malformed.json"),
            "--format",
            "json",
        ],
    )
    assert code == ExitCode.PARTIAL_SUCCESS
    assert json.loads(stdout)["run"]["status"] == "partial_success"


def test_paths_with_spaces_and_output(cli_module, tmp_path: Path):
    data_dir = tmp_path / "input with spaces"
    data_dir.mkdir()
    path = data_dir / "data file.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    output = tmp_path / "output with spaces"
    _, code, _, stderr = run(
        cli_module,
        ["--input", str(path), "--output", str(output), "--format", "markdown"],
    )
    assert code == ExitCode.SUCCESS
    assert (output / "run-summary.md").exists()
    assert "Created:" in stderr


def test_input_is_not_modified(cli_module, fixtures_dir: Path):
    path = fixtures_dir / "sample.csv"
    before = path.read_bytes()
    run(cli_module, ["--input", str(path)])
    assert path.read_bytes() == before


def test_unsupported_explicit_file(cli_module, tmp_path: Path):
    path = tmp_path / "data.pdf"
    path.write_bytes(b"not a dataset")
    _, code, _, _ = run(cli_module, ["--input", str(path)])
    assert code == ExitCode.UNSUPPORTED_FORMAT


def test_invalid_cli_values_use_argument_exit_code(cli_module):
    assert cli_module.main(["--input", "-", "--sample-size", "0"]) == ExitCode.INVALID_ARGUMENTS


def test_json_record_orientations_from_stdin(cli_module):
    for content in (
        '[{"a": 1}, {"a": 2}]',
        '{"a": [1, 2], "b": [3, 4]}',
        '{"records": [{"a": 1}]}',
        '{"a": 1, "b": "x"}',
    ):
        _, code, stdout, _ = run(
            cli_module, ["--input", "-", "--format", "json"], content
        )
        assert code == ExitCode.SUCCESS
        assert json.loads(stdout)["run"]["successful_count"] == 1


def test_stdin_reader_stops_after_limit(cli_module, monkeypatch):
    monkeypatch.setattr(cli_module, "MAX_STDIN_BYTES", 5)

    class TrackingStream:
        calls = 0

        def read(self, size):
            self.calls += 1
            return "123456" if self.calls == 1 else "should-not-be-read"

    stream = TrackingStream()
    try:
        cli_module.read_stdin_bounded(stream, "utf-8")
    except Exception as error:
        assert error.exit_code == ExitCode.PARSING_FAILURE
    else:
        raise AssertionError("expected bounded stdin error")
    assert stream.calls == 1


def test_skill_frontmatter_matches_directory():
    skill = Path(__file__).resolve().parents[1] / "skills" / "ge-108-data" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\nname: ge-108-data\n")
    assert skill.parent.name == "ge-108-data"


def test_folder_partial_success_and_recursive_discovery(cli_module, tmp_path: Path):
    (tmp_path / "valid.csv").write_text("a\n1\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "broken.json").write_text("[{", encoding="utf-8")
    _, code, stdout, _ = run(
        cli_module,
        ["--input", str(tmp_path), "--recursive", "--format", "json"],
    )
    result = json.loads(stdout)
    assert code == ExitCode.PARTIAL_SUCCESS
    assert result["run"]["successful_count"] == 1
    assert result["run"]["failed_count"] == 1


def test_cli_does_not_open_network_socket(cli_module, fixtures_dir: Path, monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", forbidden)
    _, code, _, _ = run(cli_module, ["--input", str(fixtures_dir / "sample.csv")])
    assert code == ExitCode.SUCCESS
