"""GE-108 sent-archive extraction and duplicate stringCode analysis."""

from __future__ import annotations

import re
import shutil
import stat
import tempfile
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import DefaultDict

from .models import InvalidArgumentsError, MissingInputError, OutputError, ParseInputError

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
NO_DUPLICATES_MESSAGE = "No duplicates found"
MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 10 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000


@dataclass
class Occurrence:
    file: str
    line: int
    sequence: str
    encoder: str
    product: int
    status: str = "unknown"


@dataclass
class Ge108Result:
    sent_dir: Path
    date_dir: Path
    okfile_dir: Path
    copied_archives: list[Path]
    copied_files: list[Path]
    extracted_files: list[Path]
    scanned_files: int
    total_product_count: int
    duplicate_code_count: int
    duplicate_entry_count: int
    same_status_groups: int
    mixed_status_groups: int
    reports: list[Path]


def parse_requested_date(value: str) -> datetime:
    match = DATE_PATTERN.search(value.strip())
    if not match:
        raise InvalidArgumentsError("--date must contain DD/MM/YYYY or DD-MM-YYYY")
    normalized = f"{match.group('day')}/{match.group('month')}/{match.group('year')}"
    try:
        return datetime.strptime(normalized, "%d/%m/%Y")
    except ValueError as exc:
        raise InvalidArgumentsError(f'invalid calendar date: "{value}"') from exc


def resolve_sent_dir(candidate: Path) -> Path:
    expanded = candidate.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    if expanded.is_file():
        expanded = expanded.parent
    candidates = (
        expanded / "data" / "products" / "sent",
        expanded / "products" / "sent",
        expanded / "sent",
        expanded,
    )
    for path in candidates:
        if path.is_dir():
            return path.resolve(strict=True)
    raise MissingInputError(
        f'sent directory does not exist or is inaccessible: "{candidate}"',
        path=str(candidate),
    )


def _ensure_safe_destination(path: Path, root: Path) -> None:
    resolved_root = root.resolve(strict=True)
    current = path
    while current != root.parent:
        if current.is_symlink():
            raise OutputError(f'refusing symbolic-link output path: "{current}"')
        if current == root:
            break
        current = current.parent
    resolved_parent = path.parent.resolve(strict=True)
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as exc:
        raise OutputError(f'output path escapes generated workspace: "{path}"') from exc


def _copy_file(source: Path, destination: Path, root: Path) -> None:
    _ensure_safe_destination(destination, root)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    except OSError as exc:
        raise OutputError(f'could not copy generated file: "{destination}"') from exc


def copy_matching_files(
    sent_dir: Path,
    parsed_date: datetime,
    date_dir: Path,
    okfile_dir: Path,
) -> tuple[list[Path], list[Path]]:
    prefix = parsed_date.strftime("%Y-%m-%d")
    matching = sorted(
        path for path in sent_dir.iterdir() if path.is_file() and path.name.startswith(prefix)
    )
    if not matching:
        raise MissingInputError(
            f'no root-level sent files found with date prefix "{prefix}" in "{sent_dir}"',
            path=str(sent_dir),
        )
    archives: list[Path] = []
    files: list[Path] = []
    for source in matching:
        destination_dir = date_dir if source.name.endswith(".data.zip") else okfile_dir
        destination = destination_dir / source.name
        _copy_file(source, destination, date_dir)
        (archives if source.name.endswith(".data.zip") else files).append(destination)
    return archives, files


def _validate_archive(archive: zipfile.ZipFile, archive_path: Path) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise ParseInputError(
            f'archive contains too many members: "{archive_path.name}"', path=str(archive_path)
        )
    total_size = 0
    for member in members:
        member_path = Path(member.filename)
        if not member_path.parts or member_path.is_absolute() or ".." in member_path.parts:
            raise ParseInputError(
                f'archive contains an unsafe path: "{member.filename}"', path=str(archive_path)
            )
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ParseInputError(
                f'archive contains a symbolic link: "{member.filename}"', path=str(archive_path)
            )
        total_size += member.file_size
        if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise ParseInputError(
                f'archive exceeds the uncompressed-size safety limit: "{archive_path.name}"',
                path=str(archive_path),
            )
        if member.file_size and member.compress_size == 0:
            raise ParseInputError(
                f'archive member has an unsafe compression ratio: "{member.filename}"',
                path=str(archive_path),
            )
        if member.compress_size and member.file_size / member.compress_size > MAX_COMPRESSION_RATIO:
            raise ParseInputError(
                f'archive member exceeds the compression-ratio safety limit: "{member.filename}"',
                path=str(archive_path),
            )
    return members


def extract_archives(archives: list[Path], okfile_dir: Path) -> list[Path]:
    extracted: list[Path] = []
    for archive_path in archives:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = _validate_archive(archive, archive_path)
                with tempfile.TemporaryDirectory(
                    prefix=f".{archive_path.stem}-", dir=archive_path.parent
                ) as temp_name:
                    temp_dir = Path(temp_name)
                    for member in members:
                        if member.is_dir():
                            continue
                        member_path = Path(member.filename)
                        temporary = temp_dir.joinpath(*member_path.parts)
                        temporary.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as source, temporary.open("wb") as target:
                            shutil.copyfileobj(source, target)
                        destination = okfile_dir.joinpath(*member_path.parts)
                        try:
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            _ensure_safe_destination(destination, okfile_dir)
                            if destination.exists():
                                if destination.is_dir():
                                    raise OutputError(
                                        f'generated file conflicts with directory: "{destination}"'
                                    )
                                destination.unlink()
                            shutil.move(str(temporary), destination)
                        except OutputError:
                            raise
                        except OSError as exc:
                            raise OutputError(
                                f'could not create extracted file: "{destination}"'
                            ) from exc
                        extracted.append(destination)
        except (ParseInputError, OutputError):
            raise
        except (OSError, zipfile.BadZipFile) as exc:
            raise ParseInputError(
                f'could not safely extract archive: "{archive_path}"', path=str(archive_path)
            ) from exc
    return extracted


def scan_file(
    file_path: Path,
    display_name: str,
    codes: DefaultDict[str, list[Occurrence]],
) -> int:
    product_index = 0
    pending_code: str | None = None
    last_status = "unknown"
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, 1):
                if "<Product " in line:
                    product_index += 1
                    pending_code = None
                code_match = CODE_PATTERN.search(line)
                if code_match:
                    pending_code = code_match.group(1)
                    sequence = SEQ_PATTERN.search(line)
                    encoder = ENC_PATTERN.search(line)
                    codes[pending_code].append(
                        Occurrence(
                            file=display_name,
                            line=line_number,
                            sequence=sequence.group(1) if sequence else "unknown",
                            encoder=encoder.group(1) if encoder else "unknown",
                            product=product_index,
                        )
                    )
                status_match = STATUS_PATTERN.search(line)
                if status_match:
                    last_status = status_match.group(1)
                    if pending_code and codes[pending_code]:
                        codes[pending_code][-1].status = last_status
                if STATUS_REF_PATTERN.search(line) and pending_code and codes[pending_code]:
                    codes[pending_code][-1].status = last_status
    except OSError as exc:
        raise ParseInputError(f'could not read data file: "{file_path}"', path=str(file_path)) from exc
    return product_index


def scan_files(okfile_dir: Path) -> tuple[DefaultDict[str, list[Occurrence]], int, int]:
    codes: DefaultDict[str, list[Occurrence]] = defaultdict(list)
    files = sorted(okfile_dir.rglob("*.data.ok"))
    if not files:
        raise MissingInputError(
            f'no .data.ok files found after extraction in: "{okfile_dir}"', path=str(okfile_dir)
        )
    products = sum(scan_file(path, path.relative_to(okfile_dir).as_posix(), codes) for path in files)
    return codes, products, len(files)


def _write_report(path: Path, lines: list[str], root: Path) -> None:
    _ensure_safe_destination(path, root)
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        raise OutputError(f'could not write report: "{path}"') from exc


def _detail_lines(groups: dict[str, list[Occurrence]], include_status: bool) -> list[str]:
    lines: list[str] = []
    for code in sorted(groups):
        occurrences = groups[code]
        lines.extend(["", "=================================", f"DUPLICATE CODE: {code}", f"COUNT: {len(occurrences)}"])
        for occurrence in occurrences:
            status = f" | Status: {occurrence.status}" if include_status else ""
            lines.append(
                f"File: {occurrence.file} | Product: {occurrence.product}{status} | "
                f"Sequence: {occurrence.sequence} | Encoder: {occurrence.encoder} | Line: {occurrence.line}"
            )
        if len({item.file for item in occurrences}) > 1:
            lines.append("Appears in MULTIPLE FILES")
    return lines or [NO_DUPLICATES_MESSAGE]


def _count_lines(groups: dict[str, list[Occurrence]]) -> list[str]:
    lines: list[str] = []
    for code in sorted(groups):
        occurrences = groups[code]
        lines.append(f"\nDUPLICATE: {code} (count={len(occurrences)})")
        lines.extend(f"  {item.file} : line {item.line}" for item in occurrences)
    if not groups:
        return [NO_DUPLICATES_MESSAGE]
    lines.extend(
        [
            "\n========== SUMMARY ==========",
            f"Total duplicated codes      : {len(groups)}",
            f"Total duplicate occurrences : {sum(len(items) for items in groups.values())}",
        ]
    )
    return lines


def _summary_lines(
    groups: dict[str, list[Occurrence]], total_products: int
) -> tuple[list[str], int, int]:
    statuses: Counter[str] = Counter()
    combinations: Counter[str] = Counter()
    files: Counter[str] = Counter()
    same_status = 0
    mixed_status = 0
    for occurrences in groups.values():
        values = [item.status for item in occurrences]
        unique = sorted(set(values))
        statuses.update(values)
        combinations[" | ".join(unique)] += 1
        if len(unique) == 1:
            same_status += 1
        else:
            mixed_status += 1
        files.update({item.file for item in occurrences})
    lines = [
        "Duplicate status report summary",
        "===============================",
        f"Total production count: {total_products}",
        f"Duplicate groups: {len(groups)}",
        f"Groups across multiple files: {sum(len({item.file for item in values}) > 1 for values in groups.values())}",
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
    if not groups:
        lines.extend(["", NO_DUPLICATES_MESSAGE])
    return lines, same_status, mixed_status


def analyze_sent_archives(
    sent_dir_value: Path,
    date_value: str,
    *,
    overwrite: bool = False,
) -> Ge108Result:
    sent_dir = resolve_sent_dir(sent_dir_value)
    parsed_date = parse_requested_date(date_value)
    date_dir = sent_dir / parsed_date.strftime("%d-%m-%Y")
    okfile_dir = date_dir / OKFILE_DIR_NAME
    if date_dir.exists():
        if date_dir.is_symlink() or not date_dir.is_dir():
            raise OutputError(f'refusing unsafe generated date path: "{date_dir}"')
        if not overwrite:
            raise OutputError(
                f'generated date directory already exists: "{date_dir}"; use --overwrite to rebuild it'
            )
        try:
            shutil.rmtree(date_dir)
        except OSError as exc:
            raise OutputError(f'could not rebuild generated date directory: "{date_dir}"') from exc
    try:
        date_dir.mkdir(parents=True)
        okfile_dir.mkdir()
    except OSError as exc:
        raise OutputError(f'could not create generated date directory: "{date_dir}"') from exc
    archives, files = copy_matching_files(
        sent_dir, parsed_date, date_dir, okfile_dir
    )
    extracted = extract_archives(archives, okfile_dir)
    codes, total_products, scanned_files = scan_files(okfile_dir)
    groups = {code: values for code, values in codes.items() if len(values) > 1}
    summary, same_status, mixed_status = _summary_lines(groups, total_products)
    reports = [
        okfile_dir / DETAIL_REPORT_NAME,
        okfile_dir / COUNT_REPORT_NAME,
        okfile_dir / STATUS_REPORT_NAME,
        okfile_dir / STATUS_SUMMARY_NAME,
    ]
    contents = [
        _detail_lines(groups, include_status=False),
        _count_lines(groups),
        _detail_lines(groups, include_status=True),
        summary,
    ]
    for path, lines in zip(reports, contents):
        _write_report(path, lines, date_dir)
    return Ge108Result(
        sent_dir=sent_dir,
        date_dir=date_dir,
        okfile_dir=okfile_dir,
        copied_archives=archives,
        copied_files=files,
        extracted_files=extracted,
        scanned_files=scanned_files,
        total_product_count=total_products,
        duplicate_code_count=len(groups),
        duplicate_entry_count=sum(len(values) for values in groups.values()),
        same_status_groups=same_status,
        mixed_status_groups=mixed_status,
        reports=reports,
    )
