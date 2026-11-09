"""Report source-bound file and function limits for every maintained Python root."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import TypedDict

from .source_inventory import read_source, source_paths
from .source_structure import FunctionSize, measure_source
from .structure_limits import StructureFinding, source_findings


class FunctionEvidence(TypedDict):
    """Public measurements for a function at its exact source line."""

    name: str
    line: int
    logical_lines: int
    nesting: int
    parameters: int
    tuple_arity: int


class SourceEvidence(TypedDict):
    """Measured source bytes and their file/function accounting."""

    path: str
    sha256: str
    lines: int
    functions: list[FunctionEvidence]


class StructureReport(TypedDict):
    """A complete scan refuses on any source error or unapproved limit finding."""

    ok: bool
    sources: list[SourceEvidence]
    findings: list[StructureFinding]
    errors: list[str]


def _function_evidence(function: FunctionSize) -> FunctionEvidence:
    """Project only the documented measurements into the JSON evidence."""
    return {
        "name": function.name,
        "line": function.line,
        "logical_lines": function.logical_lines,
        "nesting": function.nesting,
        "parameters": function.parameters,
        "tuple_arity": function.tuple_arity,
    }


def scan_sources(root: Path) -> StructureReport:
    """Measure a cooperating checkout; source hashes bind observations, not an atomic snapshot."""
    paths, errors = source_paths(root)
    report: StructureReport = {"ok": False, "sources": [], "findings": [], "errors": errors}
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            source = read_source(path)
            measured = measure_source(source)
        except (OSError, UnicodeError, SyntaxError, ValueError) as error:
            errors.append(f"{relative}: cannot measure source ({type(error).__name__})")
            continue
        report["sources"].append(
            {
                "path": relative,
                "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "lines": measured.lines,
                "functions": [_function_evidence(function) for function in measured.functions],
            }
        )
        report["findings"].extend(source_findings(relative, measured))
    report["ok"] = not errors and not report["findings"]
    return report


def main() -> int:
    """Emit measured JSON and refuse missing sources, measurement errors or exceeded limits."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    root: Path = arguments.root
    report = scan_sources(root)
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return int(not report["ok"])


if __name__ == "__main__":
    raise SystemExit(main())
