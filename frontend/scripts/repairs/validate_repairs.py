#!/usr/bin/env python3
"""Validate repairs queue files with no third-party dependency."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


REPAIR_FILE_RE = re.compile(r"^repair-\d{8}-\d{3}\.md$")
ARCHIVE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-repair-\d{8}-\d{3}\.md$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?$"
)
YAML_BLOCK_RE = re.compile(r"```yaml\n(.*?)\n```", re.DOTALL)
YAML_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")

STATUSES = {"todo", "processing", "fixed", "verified", "blocked", "archived"}
REGRESSION_TEST_VALUES = {"added", "updated", "not_applicable", "skipped"}
CORE_REQUIRED_FIELDS = (
    "id",
    "status",
    "created_at",
    "updated_at",
)


def is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    stripped = value.strip()
    return not stripped or (stripped.startswith("<") and stripped.endswith(">"))


def is_placeholder_line(value: str) -> bool:
    stripped = value.strip()
    normalized = re.sub(r"^(?:[-*]\s+|\d+\.\s+)", "", stripped).strip()
    return is_placeholder(normalized)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_yaml_block(text: str) -> tuple[dict[str, str], list[str]]:
    match = YAML_BLOCK_RE.search(text)
    if not match:
        return {}, ["missing fenced yaml block"]

    fields: dict[str, str] = {}
    errors: list[str] = []
    for line_number, raw_line in enumerate(match.group(1).splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match_line = YAML_LINE_RE.match(line)
        if not match_line:
            errors.append(f"invalid yaml line {line_number}: {raw_line}")
            continue
        key = match_line.group(1)
        value = (match_line.group(2) or "").strip().strip("'\"")
        if key in fields:
            errors.append(f"duplicate yaml key: {key}")
        fields[key] = value
    return fields, errors


def section_text(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def section_has_content(text: str, heading: str) -> bool:
    content = section_text(text, heading)
    if not content:
        return False
    stripped_lines = [line.strip() for line in content.splitlines() if line.strip()]
    return any(not is_placeholder_line(line) for line in stripped_lines)


def agent_notes(text: str) -> str:
    return section_text(text, "Agent Notes")


def note_has_content(notes: str, label: str) -> bool:
    lines = notes.splitlines()
    label_re = re.compile(rf"^\s*-\s+{re.escape(label)}:\s*(.*)$", re.IGNORECASE)
    for index, line in enumerate(lines):
        match = label_re.match(line)
        if not match:
            continue
        if not is_placeholder(match.group(1)):
            return True
        for follow in lines[index + 1 :]:
            if re.match(r"^-\s+[A-Za-z][A-Za-z ]+:\s*", follow):
                break
            stripped = follow.strip()
            if not stripped:
                continue
            if re.match(r"^-\s+[A-Za-z][A-Za-z ]+:\s*$", stripped):
                continue
            subvalue = stripped.split(":", 1)[1].strip() if ":" in stripped else stripped
            if not is_placeholder(subvalue):
                return True
        return False
    return False


def expected_repair_id(path: Path, include_archive: bool) -> str | None:
    if path.parent.name == "queue":
        return path.stem
    if include_archive and path.parent.name == "archive" and ARCHIVE_FILE_RE.match(path.name):
        return path.name[11:-3]
    return None


def validate_repair_file(path: Path, include_archive: bool) -> tuple[list[str], str]:
    text = read_text(path)
    fields, errors = parse_yaml_block(text)
    status = fields.get("status", "unknown")
    prefix = str(path)
    result = [f"{prefix}: {error}" for error in errors]

    if path.parent.name == "queue" and not REPAIR_FILE_RE.match(path.name):
        result.append(f"{prefix}: filename must match repair-YYYYMMDD-NNN.md")
    if path.parent.name == "archive" and include_archive and not ARCHIVE_FILE_RE.match(path.name):
        result.append(f"{prefix}: archive filename must match YYYY-MM-DD-repair-YYYYMMDD-NNN.md")

    for field in CORE_REQUIRED_FIELDS:
        if field not in fields:
            result.append(f"{prefix}: missing yaml field: {field}")

    repair_id = fields.get("id")
    expected_id = expected_repair_id(path, include_archive)
    if expected_id and repair_id != expected_id:
        result.append(f"{prefix}: id must match filename ({expected_id})")

    if status not in STATUSES:
        result.append(f"{prefix}: status must be one of {', '.join(sorted(STATUSES))}")
    if path.parent.name == "queue" and status == "archived":
        result.append(f"{prefix}: archived repairs must be moved to repairs/archive/")

    regression_test = fields.get("regression_test", "")
    if regression_test and regression_test not in REGRESSION_TEST_VALUES:
        result.append(
            f"{prefix}: regression_test must be one of {', '.join(sorted(REGRESSION_TEST_VALUES))}"
        )

    for field in ("created_at", "updated_at"):
        if is_placeholder(fields.get(field)):
            result.append(f"{prefix}: yaml field has placeholder or empty value: {field}")

    for field in ("created_at", "updated_at"):
        value = fields.get(field, "")
        if value and not DATE_RE.match(value):
            result.append(f"{prefix}: {field} must use YYYY-MM-DD")

    claimed_at = fields.get("claimed_at", "")
    if claimed_at and not DATE_TIME_RE.match(claimed_at):
        result.append(f"{prefix}: claimed_at must use YYYY-MM-DD or an ISO-like datetime")

    if status == "todo" and is_placeholder(fields.get("source")) and not section_has_content(text, "Actual"):
        result.append(f"{prefix}: status todo requires source or non-placeholder Actual section")

    if status == "processing":
        for field in ("claimed_by", "claimed_at", "run_id"):
            if is_placeholder(fields.get(field)):
                result.append(f"{prefix}: status processing requires yaml field: {field}")

    notes = agent_notes(text)
    if status == "fixed":
        if not regression_test:
            result.append(f"{prefix}: status fixed requires yaml field: regression_test")
        for label in ("Summary", "Changed files", "Verification"):
            if not note_has_content(notes, label):
                result.append(f"{prefix}: status fixed requires Agent Notes content: {label}")
        if regression_test == "skipped" and not note_has_content(notes, "Regression test"):
            result.append(f"{prefix}: skipped regression_test requires Agent Notes content")

    if status == "verified":
        if not note_has_content(notes, "User verification") and is_placeholder(fields.get("user_verified_at")):
            result.append(
                f"{prefix}: status verified requires Agent Notes content: User verification or user_verified_at"
            )

    if status == "blocked" and not note_has_content(notes, "Blocker"):
        result.append(f"{prefix}: status blocked requires Agent Notes content: Blocker")

    if status == "archived" and not note_has_content(notes, "Archive reason"):
        result.append(f"{prefix}: status archived requires Agent Notes content: Archive reason")

    return result, status


def repair_files(root: Path, include_archive: bool) -> list[Path]:
    queue_files = sorted((root / "queue").glob("*.md"))
    archive_files = sorted((root / "archive").glob("*.md")) if include_archive else []
    return queue_files + archive_files


def selected_repair_files(root: Path, values: list[str]) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    errors: list[str] = []
    for value in values:
        path = Path(value)
        if path.parent == Path(".") and value.startswith("repair-"):
            path = root / "queue" / (value if value.endswith(".md") else f"{value}.md")
        if not path.exists():
            errors.append(f"selected repair file does not exist: {value}")
            continue
        if path.name == "repair-template.md":
            errors.append(f"selected file is a template, not an active repair: {value}")
            continue
        files.append(path)
    return files, errors


def print_status(files: list[Path], statuses: list[str], root: Path) -> None:
    counts = Counter(statuses)
    print(f"Repair queue status: {root / 'queue'}")
    if not files:
        print("- active files: 0")
        return
    for status in sorted(STATUSES | set(counts)):
        if counts[status]:
            print(f"- {status}: {counts[status]}")
    for path, status in zip(files, statuses, strict=True):
        print(f"  {path}: {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate repairs queue files.")
    parser.add_argument("files", nargs="*", help="optional selected repair files or repair ids")
    parser.add_argument("--root", default="repairs", help="repair queue root directory")
    parser.add_argument("--include-archive", action="store_true", help="also validate archive/*.md")
    parser.add_argument("--status-only", action="store_true", help="print status counts without strict validation")
    args = parser.parse_args()

    root = Path(args.root)
    if not (root / "queue").is_dir():
        print(f"Repair queue invalid: missing directory: {root / 'queue'}", file=sys.stderr)
        return 1
    if args.include_archive and not (root / "archive").is_dir():
        print(f"Repair queue invalid: missing directory: {root / 'archive'}", file=sys.stderr)
        return 1

    if args.files:
        files, selection_errors = selected_repair_files(root, args.files)
    else:
        files = repair_files(root, args.include_archive)
        selection_errors = []

    errors: list[str] = list(selection_errors)
    statuses: list[str] = []

    for path in files:
        file_errors, status = validate_repair_file(path, args.include_archive)
        statuses.append(status)
        if not args.status_only:
            errors.extend(file_errors)

    if args.status_only:
        if selection_errors:
            print("Repair queue invalid:", file=sys.stderr)
            for error in selection_errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print_status(files, statuses, root)
        return 0

    if errors:
        print("Repair queue invalid:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Repair queue OK: {root / 'queue'} ({len(files)} checked file(s))")
    if files:
        print_status(files, statuses, root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
