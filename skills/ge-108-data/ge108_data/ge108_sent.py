"""GE-108 archive workflow matching the repository date_executor behavior."""

from __future__ import annotations

import re
import shutil
import stat
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DATE_PATTERN = re.compile(r"(?P<day>\d{2})[/-](?P<month>\d{2})[/-](?P<year>\d{4})")
CODE_PATTERN = re.compile(r'stringCode="([^"]*)"')
SEQ_PATTERN = re.compile(r'sequence="([^"]*)"')
ENC_PATTERN = re.compile(r'encoderId="([^"]*)"')
STATUS_PATTERN = re.compile(r'<status[^>]*description="([^"]*)"')
STATUS_REF_PATTERN = re.compile(r"<status[^>]*reference=")
OKFILE_DIR_NAME = "OKFILe"
DETAIL_REPORT_NAME = "duplicate_report.txt"
COUNT_REPORT_NAME = "duplicate_count_report.txt"
STATUS_REPORT_NAME = "duplicate_status_report.txt"
STATUS_SUMMARY_NAME = "duplicate_status_summary.txt"
NO_DUPLICATES_MESSAGE = "No duplicates found ✅"
MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 10 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000


def extract_date(text: str) -> Optional[str]:
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    return f"{match.group('day')}/{match.group('month')}/{match.group('year')}"


def parse_date(date_text: str) -> datetime:
    return datetime.strptime(date_text, "%d/%m/%Y")


def prompt_for_valid_date(initial_date: Optional[str]) -> tuple[datetime, str]:
    candidate = initial_date
    while True:
        if candidate is None:
            print("No date found in the query.")
        else:
            print(candidate)
            try:
                return parse_date(candidate), candidate
            except ValueError:
                print(f"Invalid date: {candidate}")
        candidate = input("Please enter a valid date (DD/MM/YYYY): ").strip()


def normalize_base_dir(candidate: Path) -> Path:
    expanded = candidate.expanduser()
    if str(expanded) == ".":
        expanded = Path.cwd()
    if expanded.is_file():
        expanded = expanded.parent
    for nested in (
        expanded / "data" / "products" / "sent",
        expanded / "products" / "sent",
        expanded / "sent",
    ):
        if nested.is_dir():
            return nested
    return expanded


def ensure_target_directory(directory_name: str, sent_dir: Path) -> tuple[Path, Path]:
    sent_dir.mkdir(parents=True, exist_ok=True)
    date_dir = sent_dir / directory_name
    if date_dir.is_symlink():
        raise ValueError(f"Generated date directory must not be a symbolic link: {date_dir}")
    date_dir.mkdir(exist_ok=True)
    okfile_dir = date_dir / OKFILE_DIR_NAME
    if okfile_dir.is_symlink():
        raise ValueError(f"OKFILe directory must not be a symbolic link: {okfile_dir}")
    okfile_dir.mkdir(exist_ok=True)
    return date_dir, okfile_dir


def copy_matching_files(
    parsed_date: datetime,
    date_dir: Path,
    okfile_dir: Path,
    sent_dir: Path,
) -> tuple[list[Path], list[Path]]:
    prefix = parsed_date.strftime("%Y-%m-%d")
    archives: list[Path] = []
    other_files: list[Path] = []
    for source in sent_dir.iterdir():
        if not source.is_file() or not source.name.startswith(prefix):
            continue
        destination_parent = date_dir if source.name.endswith(".data.zip") else okfile_dir
        destination = destination_parent / source.name
        if destination.is_symlink():
            raise ValueError(f"Generated destination must not be a symbolic link: {destination}")
        shutil.copy2(source, destination)
        (archives if destination_parent == date_dir else other_files).append(destination)
    return archives, other_files


def _safe_extract_archive(archive_path: Path, destination_dir: Path) -> set[Path]:
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError(f"Archive contains too many members: {archive_path}")
        total_size = 0
        for member in members:
            member_path = Path(member.filename)
            if not member_path.parts:
                continue
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Archive contains an unsafe path: {member.filename}")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"Archive contains a symbolic link: {member.filename}")
            total_size += member.file_size
            if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError(f"Archive is too large after extraction: {archive_path}")
            if member.file_size and member.compress_size == 0:
                raise ValueError(f"Archive member has an unsafe compression ratio: {member.filename}")
            if member.compress_size and member.file_size / member.compress_size > MAX_COMPRESSION_RATIO:
                raise ValueError(f"Archive member has an unsafe compression ratio: {member.filename}")

        with tempfile.TemporaryDirectory(prefix=f".{archive_path.stem}-", dir=destination_dir) as temp_name:
            temp_dir = Path(temp_name)
            top_names: set[str] = set()
            for member in members:
                member_path = Path(member.filename)
                if not member_path.parts:
                    continue
                top_names.add(member_path.parts[0])
                target = temp_dir.joinpath(*member_path.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            top_levels: set[Path] = set()
            for name in sorted(top_names):
                source = temp_dir / name
                destination = destination_dir / name
                if destination.is_symlink():
                    raise ValueError(f"Generated destination must not be a symbolic link: {destination}")
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                shutil.move(str(source), destination)
                top_levels.add(destination)
            return top_levels


def _move_path_into_directory(source: Path, target_dir: Path) -> Path:
    if source.is_symlink():
        raise ValueError(f"Extracted path must not be a symbolic link: {source}")
    destination = target_dir / source.name
    if destination.is_symlink():
        raise ValueError(f"Generated destination must not be a symbolic link: {destination}")
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in list(source.iterdir()):
            _move_path_into_directory(child, destination)
        source.rmdir()
        return destination
    if destination.exists():
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    shutil.move(str(source), destination)
    return destination


def extract_and_move_contents(date_dir: Path, okfile_dir: Path) -> list[Path]:
    moved: list[Path] = []
    for archive_path in sorted(date_dir.glob("*.data.zip")):
        top_levels = _safe_extract_archive(archive_path, date_dir)
        for extracted in sorted(top_levels, key=lambda path: (path.is_file(), str(path))):
            if extracted.exists():
                moved.append(_move_path_into_directory(extracted, okfile_dir))
    return moved


def add_occurrence(
    codes: defaultdict[str, list[dict[str, Any]]],
    code: str,
    file_path: Path,
    line_number: int,
    product_index: int,
    line: str,
) -> None:
    sequence = SEQ_PATTERN.search(line)
    encoder = ENC_PATTERN.search(line)
    codes[code].append(
        {
            "file": file_path.name,
            "line": line_number,
            "sequence": sequence.group(1) if sequence else "unknown",
            "encoder": encoder.group(1) if encoder else "unknown",
            "product": product_index,
            "status": "unknown",
        }
    )


def apply_status(
    codes: defaultdict[str, list[dict[str, Any]]], pending_code: Optional[str], status: str
) -> None:
    if pending_code and codes[pending_code]:
        codes[pending_code][-1]["status"] = status


def scan_file(file_path: Path, codes: defaultdict[str, list[dict[str, Any]]]) -> int:
    product_index = 0
    pending_code: Optional[str] = None
    last_status = "unknown"
    with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line_number, line in enumerate(handle, 1):
            if "<Product " in line:
                product_index += 1
                pending_code = None
            code_match = CODE_PATTERN.search(line)
            if code_match:
                pending_code = code_match.group(1)
                add_occurrence(codes, pending_code, file_path, line_number, product_index, line)
            status_match = STATUS_PATTERN.search(line)
            if status_match:
                last_status = status_match.group(1)
                apply_status(codes, pending_code, last_status)
            if STATUS_REF_PATTERN.search(line):
                apply_status(codes, pending_code, last_status)
    return product_index


def scan_files(base_dir: Path) -> tuple[defaultdict[str, list[dict[str, Any]]], int]:
    codes: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    products = 0
    for file_path in sorted(base_dir.rglob("*.data.ok")):
        products += scan_file(file_path, codes)
    return codes, products


def duplicate_groups(codes: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {code: values for code, values in codes.items() if len(values) > 1}


def build_detail_report(groups: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    for code, occurrences in groups.items():
        lines.extend(["", "=================================", f"DUPLICATE CODE: {code}", f"COUNT: {len(occurrences)}"])
        for item in occurrences:
            lines.append(
                f"File: {item['file']} | Product: {item['product']} | "
                f"Sequence: {item['sequence']} | Encoder: {item['encoder']} | Line: {item['line']}"
            )
        if len({item["file"] for item in occurrences}) > 1:
            lines.append("⚠ Appears in MULTIPLE FILES")
    return lines or [NO_DUPLICATES_MESSAGE]


def build_count_report(
    groups: dict[str, list[dict[str, Any]]]
) -> tuple[list[str], int, int]:
    lines: list[str] = []
    duplicate_entries = sum(len(values) for values in groups.values())
    for code, occurrences in groups.items():
        lines.append(f"\nDUPLICATE: {code} (count={len(occurrences)})")
        lines.extend(f"  {item['file']} : line {item['line']}" for item in occurrences)
    if groups:
        lines.extend(
            [
                "\n========== SUMMARY ==========",
                f"Total duplicated codes      : {len(groups)}",
                f"Total duplicate occurrences : {duplicate_entries}",
            ]
        )
    else:
        lines.append(NO_DUPLICATES_MESSAGE)
    return lines, len(groups), duplicate_entries


def build_status_report(groups: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    for code, occurrences in groups.items():
        lines.extend(["", "=================================", f"DUPLICATE CODE: {code}", f"COUNT: {len(occurrences)}"])
        for item in occurrences:
            lines.append(
                f"File: {item['file']} | Product: {item['product']} | Status: {item['status']} | "
                f"Sequence: {item['sequence']} | Encoder: {item['encoder']} | Line: {item['line']}"
            )
        if len({item["file"] for item in occurrences}) > 1:
            lines.append("⚠ Appears in MULTIPLE FILES")
    return lines or [NO_DUPLICATES_MESSAGE]


def build_status_summary(groups: dict[str, list[dict[str, Any]]], total_products: int):
    statuses: Counter[str] = Counter()
    combinations: Counter[str] = Counter()
    files: Counter[str] = Counter()
    same_status = 0
    mixed_status = 0
    for occurrences in groups.values():
        values = [item["status"] for item in occurrences]
        unique = sorted(set(values))
        statuses.update(values)
        combinations[" | ".join(unique)] += 1
        if len(unique) == 1:
            same_status += 1
        else:
            mixed_status += 1
        files.update({item["file"] for item in occurrences})
    lines = [
        "Duplicate status report summary",
        "==============================",
        f"Source report: {STATUS_REPORT_NAME}",
        f"Total production count: {total_products}",
        f"Duplicate groups: {len(groups)}",
        f"Groups across multiple files: {sum(len({item['file'] for item in values}) > 1 for values in groups.values())}",
        f"Total duplicate occurrences: {sum(len(values) for values in groups.values())}",
        f"Extra duplicate copies: {sum(len(values) - 1 for values in groups.values())}",
        f"Groups with same status only: {same_status}",
        f"Groups with mixed statuses: {mixed_status}",
        "",
        "Top statuses by occurrence:",
    ]
    lines.extend(f"- {name}: {count}" for name, count in statuses.most_common(10))
    lines.extend(["", "Top status combinations by group:"])
    lines.extend(f"- {name}: {count}" for name, count in combinations.most_common(10))
    lines.extend(["", "Top files involved in duplicate groups:"])
    lines.extend(f"- {name}: {count}" for name, count in files.most_common(10))
    lines.extend(["", "Sample duplicate groups:"])
    for code, occurrences in list(groups.items())[:5]:
        lines.append(
            f"- Code: {code} | occurrences: {len(occurrences)} | "
            f"multi-file: {len({item['file'] for item in occurrences}) > 1}"
        )
        for item in occurrences[:3]:
            lines.append(
                f"  * {item['file']} | status={item['status']} | sequence={item['sequence']} | "
                f"encoder={item['encoder']} | line={item['line']}"
            )
    if not groups:
        lines.append(NO_DUPLICATES_MESSAGE)
    return lines, statuses, combinations, files, same_status, mixed_status


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analysis_output_dir(sent_dir: Path) -> Path:
    if sent_dir.name == "sent" and sent_dir.parent.name == "products" and sent_dir.parent.parent.name == "data":
        return sent_dir.parent.parent.parent
    return sent_dir


def run_duplicate_analysis(scan_dir: Path, output_dir: Path) -> dict[str, Any]:
    reports = {
        "detail_report": output_dir / DETAIL_REPORT_NAME,
        "count_report": output_dir / COUNT_REPORT_NAME,
        "status_report": output_dir / STATUS_REPORT_NAME,
        "status_summary": output_dir / STATUS_SUMMARY_NAME,
    }
    codes, total_products = scan_files(scan_dir)
    groups = duplicate_groups(codes)
    count_lines, duplicate_codes, duplicate_entries = build_count_report(groups)
    summary_lines, statuses, combinations, files, same_status, mixed_status = build_status_summary(
        groups, total_products
    )
    write_lines(reports["detail_report"], build_detail_report(groups))
    write_lines(reports["count_report"], count_lines)
    write_lines(reports["status_report"], build_status_report(groups))
    write_lines(reports["status_summary"], summary_lines)
    return {
        **reports,
        "total_product_count": total_products,
        "duplicate_code_count": duplicate_codes,
        "duplicate_entry_count": duplicate_entries,
        "same_status_groups": same_status,
        "mixed_status_groups": mixed_status,
        "top_status": statuses.most_common(1)[0] if statuses else None,
        "top_status_combination": combinations.most_common(1)[0] if combinations else None,
        "top_file": files.most_common(1)[0] if files else None,
    }


def run(query: str, sent_dir: Path) -> Path:
    parsed_date, provided_date = prompt_for_valid_date(extract_date(query))
    date_dir, okfile_dir = ensure_target_directory(provided_date.replace("/", "-"), sent_dir)
    archives, other_files = copy_matching_files(parsed_date, date_dir, okfile_dir, sent_dir)
    moved = extract_and_move_contents(date_dir, okfile_dir)
    analysis = run_duplicate_analysis(okfile_dir, analysis_output_dir(sent_dir))
    print(f"Created or verified date directory: {date_dir}")
    print(f"Created or verified OKFILe directory: {okfile_dir}")
    print(
        f"Copied {len(archives)} .data.zip file(s) to {date_dir.name}, extracted them there, and "
        f"copied {len(other_files)} other file(s) to {OKFILE_DIR_NAME} for {provided_date}."
    )
    if moved:
        print(f"Moved {len(moved)} extracted path(s) into {OKFILE_DIR_NAME}.")
    print(f"Duplicate report written to: {analysis['detail_report']}")
    print(f"Duplicate count report written to: {analysis['count_report']}")
    print(f"Duplicate status report written to: {analysis['status_report']}")
    print(f"Duplicate status summary written to: {analysis['status_summary']}")
    print(f"Total production count: {analysis['total_product_count']}")
    print(f"Duplicate groups found: {analysis['duplicate_code_count']}")
    print(f"Total duplicate occurrences: {analysis['duplicate_entry_count']}")
    print(f"Groups with same status only: {analysis['same_status_groups']}")
    print(f"Groups with mixed statuses: {analysis['mixed_status_groups']}")
    print(f"Top status: {analysis['top_status']}")
    print(f"Top status combination: {analysis['top_status_combination']}")
    print(f"Top file: {analysis['top_file']}")
    return okfile_dir
