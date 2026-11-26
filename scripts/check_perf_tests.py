#!/usr/bin/env python3
"""Check that the release perf job ran every wall-clock bound that exists (flyingrobots/taskalisk#120).

Usage: python3 scripts/check_perf_tests.py LISTED RAN

LISTED is the output of `cargo test ... -- --ignored --list perf_`, and RAN the output of the same
command without `--list`, each with stderr included, so that cargo's `Running ... (binary)` lines say
which test binary each test belongs to. A test is its binary and its name: the same name in two
binaries is two tests.

The check passes when at least one perf_ test is listed and every listed one passed. It prints the
count in every outcome, and names each listed test that did not pass. Exit 0: pass; 1: fail;
2: usage.
"""
import re
import sys
from pathlib import Path

# cargo: `     Running unittests src/lib.rs (target/release/.../issue_dag_core-28df925872dceff0)`.
RUNNING = re.compile(r"^\s+Running .*\((?P<binary>[^)]+)\)\s*$")
# libtest --list: `plan::tests::perf_a_chain: test`.
LISTED = re.compile(r"^(?P<name>\S*perf_\S*): test$")
# libtest run: `test plan::tests::perf_a_chain ... ok`; FAILED and ignored lines do not match.
PASSED = re.compile(r"^test (?P<name>\S*perf_\S*) \.\.\. ok$")


def tests(output, pattern):
    """The (binary, name) pairs of `output` lines that match `pattern`."""
    found = set()
    binary = None
    for line in output.splitlines():
        running = RUNNING.match(line)
        if running:
            binary = running.group("binary")
            continue
        match = pattern.match(line)
        if match:
            found.add((binary, match.group("name")))
    return found


def check(listed, ran):
    """(ok, message) for the two outputs."""
    expected = tests(listed, LISTED)
    passed = tests(ran, PASSED)
    missing = sorted(expected - passed, key=lambda t: (t[0] or "", t[1]))
    lines = ["perf_ tests passed: {} of {}".format(len(expected & passed), len(expected))]
    if not expected:
        lines.append("no perf_ test is listed: the filter matched nothing")
    lines += ["did not pass: {} ({})".format(name, binary) for binary, name in missing]
    return bool(expected) and not missing, "\n".join(lines)


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
