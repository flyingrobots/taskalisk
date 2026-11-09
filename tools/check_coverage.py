"""Enforce separate statement and branch floors for maintained Python scopes."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import cast

CRITICAL_MODULES = (
    "authorization",
    "cli",
    "identities",
    "frontmatter",
    "issue_refs",
    "github",
    "discovery",
    "process",
    "modes",
    "output",
    "spec_checks",
    "spec_file",
    "spec_values",
)
CORE = "skills/taskalisk/scripts/taskalisk_core/"
ROOTS = ("skills/taskalisk/scripts", "tests", "tools")
COUNT_KEYS = (
    "num_statements",
    "covered_lines",
    "missing_lines",
    "num_branches",
    "covered_branches",
    "missing_branches",
)


def object_fields(value: object) -> dict[str, object] | None:
    """Copy a JSON object only after checking its container and every key."""
    if not isinstance(value, dict):
        return None
    # The isinstance check establishes dict; object/object asserts no domain type.
    entries = cast("dict[object, object]", value)
    fields: dict[str, object] = {}
    for key, entry in entries.items():
        if not isinstance(key, str):
            return None
        fields[key] = entry
    return fields


def read_counts(value: object) -> dict[str, int] | None:
    """Validate integral, nonnegative and internally consistent coverage counts."""
    fields = object_fields(value)
    if fields is None:
        return None
    counts: dict[str, int] = {}
    for key in COUNT_KEYS:
        count = fields.get(key)
        if type(count) is not int or count < 0:
            return None
        counts[key] = count
    for total, covered, missing in (
        ("num_statements", "covered_lines", "missing_lines"),
        ("num_branches", "covered_branches", "missing_branches"),
    ):
        if counts[covered] + counts[missing] != counts[total]:
            return None
    return counts


def required_files(root: Path) -> list[str]:
    """Include maintained source files and the explicitly required critical scopes."""
    expected = {f"{CORE}{module}.py" for module in CRITICAL_MODULES}
    for directory in ROOTS:
        expected.update(
            path.relative_to(root).as_posix() for path in (root / directory).rglob("*.py")
        )
    return sorted(expected)


def floor_for(path: str) -> int:
    """Assign critical module families 95%, and other maintained Python 90%."""
    if path.startswith("tools/"):
        return 95
    stem = Path(path).stem
    critical = path.startswith(CORE) and any(
        stem == module or stem.startswith(f"{module}_") for module in CRITICAL_MODULES
    )
    return 95 if critical else 90


def has_executable_source(path: Path) -> bool:
    """Distinguish empty/docstring modules from unmeasured executable source."""
    module = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        for node in module.body
    )


def check_file(path: str, entry: object, root: Path) -> list[str]:
    """Check each measure independently using exact integer ratios."""
    fields = object_fields(entry)
    counts = read_counts(fields.get("summary")) if fields is not None else None
    if counts is None:
        return [f"{path}: invalid counts"]
    try:
        if not counts["num_statements"] and has_executable_source(root / path):
            return [f"{path}: no statements measured for executable source"]
    except (OSError, UnicodeError, SyntaxError):
        return [f"{path}: cannot inspect source"]
    failures: list[str] = []
    floor = floor_for(path)
    for measure, covered, total in (
        ("statements", counts["covered_lines"], counts["num_statements"]),
        ("branches", counts["covered_branches"], counts["num_branches"]),
    ):
        # With zero opportunities, consistency above requires zero covered/missing.
        if covered * 100 < floor * total:
            failures.append(f"{path}: {measure} {covered}/{total} below {floor}%")
    return failures


def check_report(report: object, root: Path) -> list[str]:
    """Reject incomplete measurements rather than treating them as an empty success."""
    fields = object_fields(report)
    if fields is None:
        return ["invalid coverage report: expected an object"]
    meta = object_fields(fields.get("meta"))
    files = object_fields(fields.get("files"))
    if meta is None or meta.get("branch_coverage") is not True or files is None:
        return ["invalid coverage report: branch measurements and files are required"]
    failures: list[str] = []
    for path in required_files(root):
        if not (root / path).is_file():
            failures.append(f"{path}: required source is missing")
        elif path not in files:
            failures.append(f"{path}: missing coverage")
        else:
            failures.extend(check_file(path, files[path], root))
    return failures


def main() -> int:
    """Read a Coverage.py JSON report and print precise gate failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    report_path: Path = arguments.report
    root: Path = arguments.root
    try:
        report: object = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        # policy-exception: PY-COVERAGE-OUTPUT -- Emit the CLI's diagnostic protocol.
        print(f"invalid coverage report: {error}")  # noqa: T201
        return 1
    failures = check_report(report, root)
    for failure in failures:
        # policy-exception: PY-COVERAGE-OUTPUT -- Emit the CLI's diagnostic protocol.
        print(failure)  # noqa: T201
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
