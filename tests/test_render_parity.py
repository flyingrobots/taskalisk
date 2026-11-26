"""The fixtures of the Rust renderer's parity test (crates/taskalisk/tests/parity.rs).

- `tests/fixtures/render/python/` is what `tests/capture_render_parity.py` writes now: the
  Python's result lines for each agreed graph case of the corpus. A change to the compiler's
  output fails here until the fixtures are recaptured.
- `tests/fixtures/render/rust/` is the Rust rendering of the same cases, which the Rust test
  holds byte for byte. Each of its lines must validate against the exact schema its `_schema`
  names, once the writer's envelope (`t`, `seq`, `run`) is added. The renderer has no gap left:
  the trust gate's reasons (flyingrobots/taskalisk#46) were the last.
"""
import json
import re
import unittest

import capture_render_parity as capture
import parley_lines as pl
from parley_emit import validate_line

RUST = capture.FIXTURES / "rust"


# Not a gap but an intended difference: a frontmatter finding is read by its `code` and `subject`;
# its message is prose that neither the schema nor the specification fixes, so the Rust one (the
# core's fixed text, one per rule) differs from the Python's (one per message, with the value).
INTENDED_DIFFERENCES = {"frontmatter.violation": "message", "frontmatter.warning": "message"}


class PythonFixtures(unittest.TestCase):
    def test_fixtures_are_what_the_compiler_writes_now(self):
        expected = capture.expected_fixtures()
        on_disk = {p.stem: p.read_text() for p in (capture.FIXTURES / "python").glob("*.jsonl")}
        self.assertEqual(sorted(on_disk), sorted(expected), "recapture: python3 tests/capture_render_parity.py")
        stale = [name for name in expected if on_disk[name] != expected[name]]
        self.assertEqual(stale, [], "recapture: python3 tests/capture_render_parity.py")

    def test_variant_bundles_are_what_the_script_writes_now(self):
        expected = capture.expected_bundles()
        on_disk = {p.stem: p.read_text() for p in (capture.FIXTURES / "bundles").glob("*.json")}
        self.assertEqual(on_disk, expected, "recapture: python3 tests/capture_render_parity.py")


class RustRecordings(unittest.TestCase):
    def test_one_recording_per_python_fixture(self):
        self.assertEqual(sorted(p.stem for p in RUST.glob("*.jsonl")),
                         sorted(p.stem for p in (capture.FIXTURES / "python").glob("*.jsonl")))

    def test_every_line_validates(self):
        checked = 0
        for path in sorted(RUST.glob("*.jsonl")):
            for n, line in enumerate(pl.parse(path.read_text(), path.name), 1):
                for key in ("t", "seq", "run"):
                    self.assertNotIn(key, line, f"{path.name}:{n}: the envelope is the writer's")
                full = {**line, "t": 0, "seq": n, "run": "parity"}
                result = validate_line(full, pl.TOOL_SCHEMAS)
                errors = {re.sub(r"/\d+", "/*", str(e)) for e in result.errors}
                self.assertFalse(result.unsupported, f"{path.name}:{n}: {result.unsupported}")
                self.assertEqual(errors, set(), f"{path.name}:{n}: {line}")
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
