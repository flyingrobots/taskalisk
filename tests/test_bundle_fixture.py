"""The committed observation bundle of this repository (flyingrobots/taskalisk#59).

`tests/fixtures/bundles/flyingrobots-taskalisk.bundle.json` was captured by the Rust binary's
`plan --capture-bundle` from flyingrobots/taskalisk, read-only. The Rust suite
(`crates/taskalisk/tests/replay.rs`) replans from it with reads disabled; this test holds it to
the corpus tooling's own bundle checker, written independently of the Rust loader, and checks that
nothing secret or machine-local was committed with it.

Run: python3 -m unittest discover -s tests
"""
import json
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from corpus import bundle as ob  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "bundles" / "flyingrobots-taskalisk.bundle.json"

# GitHub token prefixes (classic, OAuth, user-to-server, server-to-server, refresh, fine-grained).
TOKEN = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")


class CommittedBundle(unittest.TestCase):
    def setUp(self):
        self.text = FIXTURE.read_text(encoding="utf-8")
        self.bundle = json.loads(self.text)

    def test_it_is_a_bundle_the_corpus_checker_accepts(self):
        self.assertEqual(ob.validate(self.bundle), [])
        self.assertEqual(self.bundle["parameters"]["home"], "flyingrobots/taskalisk")

    def test_it_holds_no_token_and_no_machine_local_path(self):
        self.assertIsNone(TOKEN.search(self.text))
        for local in ("/Users/", "/home/", "C:\\"):
            self.assertNotIn(local, self.text)


if __name__ == "__main__":
    unittest.main()
