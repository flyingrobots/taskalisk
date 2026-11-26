#!/usr/bin/env python3
"""Validate Parley lines read from stdin against the exact schema each names.

Not a test (unittest discovery skips it). The Rust binary's tests
(`crates/taskalisk/tests/cli.rs`) pipe a run's stdout, stderr and receipt lines here, so they are
checked with the vendored writer's bounded checker and the schemas under
`skills/taskalisk/schemas/`, the same check `tests/parley_lines.py` gives the Python's lines.
Prints one problem per line and exits 1 when any line does not validate or is not a JSON object.
"""
import json
import sys

import parley_lines as pl


def main() -> int:
    text = sys.stdin.read()
    try:
        lines = pl.parse(text, "stdin")
    except AssertionError as exc:
        print(exc)
        return 1
    bad = pl.problems(lines)
    for problem in bad:
        print(json.dumps(problem, default=str))
    if not lines:
        print("no lines to validate")
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
