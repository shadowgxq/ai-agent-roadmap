#!/usr/bin/env python3
"""Lightweight Manager plan validator with no third-party dependency."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT_KEYS = ("updated_at", "current", "requirements", "openspec", "batches")
CURRENT_KEYS = ("title", "batch", "wave", "next")


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        raise ValueError(f"missing file: {path}")
    return path.read_text(encoding="utf-8").splitlines()


def top_level_keys(lines: list[str]) -> set[str]:
    keys: set[str] = set()
    for line in lines:
        if not line or line.startswith("#") or line.startswith(" "):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):", line)
        if match:
            keys.add(match.group(1))
    return keys


def section_lines(lines: list[str], section: str) -> list[str]:
    start = None
    for index, line in enumerate(lines):
        if line == f"{section}:":
            start = index + 1
            break
    if start is None:
        return []

    result: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        result.append(line)
    return result


def ids_in_section(lines: list[str], section: str) -> list[str]:
    ids: list[str] = []
    for line in section_lines(lines, section):
        # 只统计 section 顶层列表项的 id，排除嵌套项（如 batch 内的 wave id）
        match = re.match(r"^ {2}-\s+id:\s*([A-Za-z0-9_-]+)\s*$", line)
        if match:
            ids.append(match.group(1))
    return ids


def current_refs(lines: list[str]) -> tuple[str | None, str | None]:
    batch = None
    wave = None
    for line in section_lines(lines, "current"):
        stripped = line.strip()
        if stripped.startswith("batch:"):
            value = stripped.split(":", 1)[1].strip()
            batch = None if value in {"null", ""} else value.strip("'\"")
        if stripped.startswith("wave:"):
            value = stripped.split(":", 1)[1].strip()
            wave = None if value in {"null", ""} else value.strip("'\"")
    return batch, wave


def validate_plan(path: Path) -> list[str]:
    lines = read_lines(path)
    errors: list[str] = []

    keys = top_level_keys(lines)
    for key in ROOT_KEYS:
        if key not in keys:
            errors.append(f"missing top-level key: {key}")

    current = "\n".join(section_lines(lines, "current"))
    for key in CURRENT_KEYS:
        if not re.search(rf"^\s+{re.escape(key)}:", current, re.MULTILINE):
            errors.append(f"missing current.{key}")

    requirement_ids = ids_in_section(lines, "requirements")
    openspec_ids = ids_in_section(lines, "openspec")
    batch_ids = ids_in_section(lines, "batches")
    current_batch, _current_wave = current_refs(lines)

    if current_batch and current_batch not in batch_ids:
        errors.append(f"current.batch references missing batch: {current_batch}")

    duplicates = []
    for label, values in (
        ("requirements", list(requirement_ids)),
        ("openspec", list(openspec_ids)),
        ("batches", list(batch_ids)),
    ):
        if len(values) != len(set(values)):
            duplicates.append(label)
    for label in duplicates:
        errors.append(f"duplicate ids detected in {label}")

    return errors


def main() -> int:
    plan_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("manager/plan.yaml")

    try:
        errors = validate_plan(plan_path)
    except ValueError as exc:
        print(f"Manager plan invalid: {exc}", file=sys.stderr)
        return 1

    if errors:
        print("Manager plan invalid:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Manager plan OK: {plan_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
