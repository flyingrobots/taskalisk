"""The vendored Parley writer is the file flyingrobots/parley published at the pinned commit
(flyingrobots/taskalisk#77).

`Vendored.test_copy_matches_its_pin` (tests/test_parley_output.py) proves only that the copy has not
drifted from its pin; both live here, so a changed writer with a recomputed pin passes it. This module
tests the check that proves provenance, `scripts/check_vendored_writer.py`, offline with an injected
fetch, and runs it against GitHub only when TASKALISK_UPSTREAM_CHECK=1 (CI sets it). Offline, that one
test is reported as skipped, never as passed.
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "taskalisk" / "scripts"
SPEC = importlib.util.spec_from_file_location("check_vendored_writer", ROOT / "scripts" / "check_vendored_writer.py")
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def pin_for(data, base):
    """A pin recomputed for `data`, as someone changing the writer would write it."""
    return dict(base, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))


class UpstreamProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.pin = json.loads((SCRIPTS / "parley_emit.pin.json").read_text())
        self.copy = (SCRIPTS / "parley_emit.py").read_bytes()

    def test_the_url_names_the_pinned_commit_and_path(self):
        self.assertEqual(check.upstream_url(self.pin),
                         f"https://raw.githubusercontent.com/flyingrobots/parley/{self.pin['parley_commit']}"
                         "/packages/parley-emit-py/parley_emit.py")

    def test_an_unmodified_copy_passes(self):
        self.assertEqual(check.problems(self.pin, self.copy, lambda url: self.copy), [])

    def test_a_modified_writer_with_a_recomputed_pin_fails(self):
        changed = self.copy + b"\n# a change made here\n"
        problems = check.problems(pin_for(changed, self.pin), changed, lambda url: self.copy)
        self.assertTrue(problems)
        self.assertTrue(any("upstream" in p for p in problems), problems)

    def test_a_copy_that_drifted_from_its_pin_fails(self):
        self.assertTrue(check.problems(self.pin, self.copy + b"x", lambda url: self.copy))

    def test_a_failed_fetch_is_an_error_never_a_pass(self):
        def offline(url):
            raise OSError("network is unreachable")
        problems = check.problems(self.pin, self.copy, offline)
        self.assertEqual(len(problems), 1)
        self.assertIn("could not fetch", problems[0])

    def test_a_pin_without_a_commit_is_refused(self):
        pin = dict(self.pin)
        del pin["parley_commit"]
        self.assertTrue(check.problems(pin, self.copy, lambda url: self.copy))

    @unittest.skipUnless(os.environ.get("TASKALISK_UPSTREAM_CHECK") == "1",
                         "upstream provenance not checked: set TASKALISK_UPSTREAM_CHECK=1 (needs network; CI sets it)")
    def test_the_vendored_writer_is_upstream_at_its_pinned_commit(self):
        self.assertEqual(check.problems(self.pin, self.copy, check.fetch), [])


if __name__ == "__main__":
    unittest.main()
