#!/usr/bin/env python3
"""Validate Parley lines read from stdin against the exact schema each names.

Not a test (unittest discovery skips it). The Rust binary's tests
(`crates/taskalisk/tests/cli.rs`) pipe a run's stdout, stderr and receipt lines here, so they are
checked with the vendored writer's bounded checker and the schemas under
`skills/taskalisk/schemas/`, the same check `tests/parley_lines.py` gives the Python's lines.

With `--allow-render-gaps`, a `taskalisk.finding` line may lack exactly what the Rust renderer
cannot write yet, as `tests/test_render_parity.py` declares it (FINDING_GAPS: the trust gate's
reasons, flyingrobots/taskalisk#46); every other error still fails.

Prints one problem per line and exits 1 when any line does not validate or is not a JSON object.
"""
import json
import re
import sys

import parley_lines as pl  # puts the vendored writer on the path

pe = pl.pe


def allowed(line, gaps):
    if gaps is None or not isinstance(line, dict) or line.get("_schema", {}).get("id") != "taskalisk.finding":
        return set()
    return gaps.get(line.get("code"), set())


def main(argv) -> int:
    gaps = None
    if "--allow-render-gaps" in argv:
        from test_render_parity import FINDING_GAPS
        gaps = FINDING_GAPS
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
        result = pe.validate_line(line, pl.TOOL_SCHEMAS)
        errors = {re.sub(r"/\d+", "/*", str(e)) for e in result.errors}
        if result.unsupported or not errors <= allowed(line, gaps):
            bad += 1
            print(json.dumps([line.get("_schema"), line.get("event"), sorted(errors), result.unsupported], default=str))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
