#!/usr/bin/env python3
"""Check that the release perf job ran its wall-clock bounds.

Usage: python3 scripts/check_perf_tests.py LISTED RAN

LISTED is the output of `cargo test ... -- --ignored --list perf_` and RAN that of the run.
"""
import re
import sys
from pathlib import Path

PASSED = re.compile(r"^test .*perf_.* \.\.\. ok$")
EXPECTED = 6


def check(listed, ran):
    """(ok, message) for the two outputs."""
    count = sum(1 for line in ran.splitlines() if PASSED.match(line))
    return count >= EXPECTED, "perf_ tests passed: {}".format(count)


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    listed, ran = (Path(p).read_text(encoding="utf-8") for p in argv)
    ok, message = check(listed, ran)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
