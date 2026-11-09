"""Apply the repository's file and function limits to measured Python source."""

from __future__ import annotations

from typing import TypedDict

from .source_structure import SourceSize


class StructureFinding(TypedDict):
    """One exceeded bound tied to its precise source and function identity."""

    path: str
    symbol: str
    line: int
    rule: str
    observed: int
    limit: int


def source_findings(path: str, source: SourceSize) -> list[StructureFinding]:
    """Return all exceeded bounds; no exception is implicitly approved here."""
    findings: list[StructureFinding] = []
    limits = [
        ("PY-FILE-LOCALITY", 300),
        ("PY-FILE-HARD", 750 if path.startswith("tests/") else 500),
    ]
    for rule, limit in limits:
        if source.lines > limit:
            findings.append(
                {
                    "path": path,
                    "symbol": "<module>",
                    "line": 1,
                    "rule": rule,
                    "observed": source.lines,
                    "limit": limit,
                }
            )
    for function in source.functions:
        bounds = (
            ("PY-FUNCTION-REVIEW", function.logical_lines, 40),
            ("PY-FUNCTION-LINES", function.logical_lines, 60),
            ("PY-FUNCTION-NESTING", function.nesting, 3),
            ("PY-FUNCTION-PARAMETERS", function.parameters, 5),
            ("PY-FUNCTION-TUPLE", function.tuple_arity, 3),
        )
        for rule, observed, limit in bounds:
            if observed > limit:
                findings.append(
                    {
                        "path": path,
                        "symbol": function.name,
                        "line": function.line,
                        "rule": rule,
                        "observed": observed,
                        "limit": limit,
                    }
                )
    return findings
