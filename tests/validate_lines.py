#!/usr/bin/env python3
"""Validate Parley lines read from stdin against the exact schema each names.

Not a test (unittest discovery skips it). The Rust binary's tests
(`crates/taskalisk/tests/cli.rs`) pipe a run's stdout, stderr and receipt lines here, so they are
checked with the vendored writer's bounded checker and the schemas under
`skills/taskalisk/schemas/` and its `binary/` (decision D22), the same check `tests/parley_lines.py` gives the Python's lines.

Prints one problem per line and exits 1 when any line does not validate or is not a JSON object.
"""
import json
import re
import sys

import parley_lines as pl  # puts the vendored writer on the path

pe = pl.pe


def main(argv) -> int:
    if argv:
        print(f"no arguments are taken: {argv}")
        return 1
    text = sys.stdin.read()
    try:
        lines = pl.parse(text, "stdin")
    except AssertionError as exc:
        print(exc)
        return 1
    if not lines:
        print("no lines to validate")
        return 1
    bad = 0
    for line in lines:
        result = pe.validate_line(line, pl.ALL_SCHEMAS)
        errors = {re.sub(r"/\d+", "/*", str(e)) for e in result.errors}
        if result.unsupported or errors:
            bad += 1
            print(json.dumps([line.get("_schema"), line.get("event"), sorted(errors), result.unsupported], default=str))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
