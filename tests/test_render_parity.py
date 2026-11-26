"""The fixtures of the Rust renderer's parity test (crates/taskalisk/tests/parity.rs).

- `tests/fixtures/render/python/` is what `tests/capture_render_parity.py` writes now: the
  Python's result lines for each agreed graph case of the corpus. A change to the compiler's
  output fails here until the fixtures are recaptured.
- `tests/fixtures/render/rust/` is the Rust rendering of the same cases, which the Rust test
  holds byte for byte. Each of its lines must validate against the exact schema its `_schema`
  names, once the writer's envelope (`t`, `seq`, `run`) is added, except that a field the Rust
  renderer cannot write yet may be missing (RUST_GAPS, FINDING_GAPS): the trust gate's reasons
  (flyingrobots/taskalisk#46) and an `artifact_hash` beyond the core's reach.
"""
import json
import re
import unittest

import capture_render_parity as capture
import parley_lines as pl
from parley_emit import validate_line

RUST = capture.FIXTURES / "rust"

# {schema id: the errors allowed}; `*` is any list index; a finding's depend on its code. The Rust
# rendering here is given a display input, so only what the core cannot know yet is missing:
# `artifact_hash` where the 1.x document holds the Python's frontmatter messages or trust reasons
# (flyingrobots/taskalisk#46) or a cycle's discovery findings (flyingrobots/taskalisk#44).
RUST_GAPS = {
    "taskalisk.plan": {"/ is missing artifact_hash"},
}
# The trust gate's reasons: flyingrobots/taskalisk#46.
FINDING_GAPS = {
    "issue.untrusted": {"/ is missing message"} | {f"/detail is missing {f}" for f in ("url", "state", "author", "reasons", "referenced_by")},
    "pull_request.untrusted": {"/ is missing message"},
}

# Not a gap but an intended difference: a frontmatter finding is read by its `code` and `subject`;
# its message is prose that neither the schema nor the specification fixes, so the Rust one (the
# core's fixed text, one per rule) differs from the Python's (one per message, with the value).
INTENDED_DIFFERENCES = {"frontmatter.violation": "message", "frontmatter.warning": "message"}


def allowed(line):
    if line["_schema"]["id"] == "taskalisk.finding":
        return FINDING_GAPS.get(line["code"], set())
    return RUST_GAPS.get(line["_schema"]["id"], set())


class PythonFixtures(unittest.TestCase):
    def test_fixtures_are_what_the_compiler_writes_now(self):
        expected = capture.expected_fixtures()
        on_disk = {p.stem: p.read_text() for p in (capture.FIXTURES / "python").glob("*.jsonl")}
        self.assertEqual(sorted(on_disk), sorted(expected), "recapture: python3 tests/capture_render_parity.py")
        stale = [name for name in expected if on_disk[name] != expected[name]]
        self.assertEqual(stale, [], "recapture: python3 tests/capture_render_parity.py")


class RustRecordings(unittest.TestCase):
    def test_one_recording_per_python_fixture(self):
        self.assertEqual(sorted(p.stem for p in RUST.glob("*.jsonl")),
                         sorted(p.stem for p in (capture.FIXTURES / "python").glob("*.jsonl")))

    def test_every_line_validates_but_for_the_declared_gaps(self):
        checked = 0
        for path in sorted(RUST.glob("*.jsonl")):
            for n, line in enumerate(pl.parse(path.read_text(), path.name), 1):
                for key in ("t", "seq", "run"):
                    self.assertNotIn(key, line, f"{path.name}:{n}: the envelope is the writer's")
                full = {**line, "t": 0, "seq": n, "run": "parity"}
                result = validate_line(full, pl.TOOL_SCHEMAS)
                errors = {re.sub(r"/\d+", "/*", str(e)) for e in result.errors}
                self.assertFalse(result.unsupported, f"{path.name}:{n}: {result.unsupported}")
                self.assertLessEqual(errors, allowed(line), f"{path.name}:{n}: {line}")
                checked += 1
        self.assertGreater(checked, 1000)

    def test_frontmatter_findings_differ_only_in_their_message(self):
        def keys(path):
            return {(l["code"], l["subject"]) for l in pl.parse(path.read_text(), path.name)
                    if l["event"] == "finding" and l["code"] in INTENDED_DIFFERENCES}
        compared = 0
        for path in sorted(RUST.glob("*.jsonl")):
            rust = keys(path)
            self.assertEqual(rust, keys(capture.FIXTURES / "python" / path.name), path.name)
            compared += len(rust)
        self.assertGreater(compared, 10)


if __name__ == "__main__":
    unittest.main()
