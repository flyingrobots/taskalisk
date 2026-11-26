"""The issue-dag/2 conformance corpus (flyingrobots/taskalisk#26).

scripts/corpus/ turns scenarios into observation bundles, runs the Python compiler offline against
them, and checks the corpus. The corpus itself is the specification repository's; a copy of that
repository's specification and corpus is vendored under tests/fixtures/issue-dag/, pinned by the
corpus digest, so this suite runs offline.

Run: python3 -m unittest discover -s tests
"""
import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import parley_lines as pl
from test_taskalisk import BUNNY, ECHO, HOME, SCRIPT, STRANGER, Harness, closing, fm, issue, plan_state

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from corpus import bundle as ob  # noqa: E402
from corpus import check, digest, forge, generate, spec  # noqa: E402

SPEC_COPY = pathlib.Path(__file__).resolve().parent / "fixtures" / "issue-dag"


def signature(result):
    """What two runs of the 1.x compile must agree on, without titles, URLs or hashes."""
    src = result.get("source", {})
    waves = result.get("waves", {})
    nodes = {n["id"]: (n["status"], n["priority_score"], n["completed_parents"], n["open_parents"], n["opaque"], n["untrusted"],
                       n["holds"], n["meters"]) for items in waves.values() for n in items}
    return {
        "ok": result.get("ok"),
        "nodes": nodes,
        "waves": {k: [n["id"] for n in v] for k, v in waves.items()},
        "edges": [(e["from"], e["to"]) for e in result.get("edges", [])],
        "redundant": [(e["from"], e["to"]) for e in result.get("transitive_redundant_edges_removed", [])],
        "batch": [b["id"] for b in result.get("conflict_free_frontier_batch", [])],
        "skipped": result.get("batch_skipped", []),
        "critical_path": result.get("metrics", {}).get("critical_path"),
        "merged_count": result.get("metrics", {}).get("merged_count"),
        "cyclic": result.get("cyclic_nodes"),
        "unknown": result.get("unknown_dependencies"),
        "violations": (result.get("frontmatter") or {}).get("violations"),
        "warnings": (result.get("frontmatter") or {}).get("warnings"),
        "containers": [c["id"] for c in src.get("containers_excluded", [])],
        "unmodeled": [u["id"] for u in src.get("unmodeled_open_issues", [])],
        "untrusted": [u["id"] for u in src.get("untrusted_issues", [])],
        "untrusted_prs": [p["number"] for p in src.get("untrusted_linked_prs", [])],
        "opaque": [o["id"] for o in src.get("opaque_nodes", [])],
        "not_planned": [(n["parent"], n["child"]) for n in src.get("not_planned_parents", [])],
    }


class BundleFormat(unittest.TestCase):
    """corpus/bundle.md: the observation bundle."""

    def bundle(self):
        return ob.from_fake_state(plan_state(), roots=[f"{HOME}#9"])

    def test_a_converted_state_is_a_valid_bundle(self):
        self.assertEqual(ob.validate(self.bundle()), [])

    def test_the_version_field_is_required(self):
        b = self.bundle()
        del b["bundle"]
        self.assertTrue(any("bundle" in p for p in ob.validate(b)))

    def test_an_observation_is_a_value_or_unavailable_never_empty(self):
        b = self.bundle()
        b["observations"]["home_open_pull_requests"] = {}
        self.assertTrue(any("home_open_pull_requests" in p for p in ob.validate(b)))
        b["observations"]["home_open_pull_requests"] = {"value": [], "unavailable": "rate limited"}
        self.assertTrue(any("home_open_pull_requests" in p for p in ob.validate(b)))
        b["observations"]["home_open_pull_requests"] = {"unavailable": ""}
        self.assertTrue(any("home_open_pull_requests" in p for p in ob.validate(b)))

    def test_references_are_canonical(self):
        b = self.bundle()
        b["observations"]["issues"]["Flyingrobots/Geordi#1"] = b["observations"]["issues"].pop(f"{HOME}#1")
        self.assertTrue(any("canonical" in p for p in ob.validate(b)))

    def test_the_home_repository_is_in_the_read_scope(self):
        b = self.bundle()
        b["parameters"]["read_scope"] = {"owners": [], "repositories": []}
        self.assertTrue(any("read scope" in p for p in ob.validate(b)))

    def test_a_rootless_run_records_the_home_listing(self):
        b = ob.from_fake_state(plan_state())
        self.assertEqual(sorted(b["observations"]["home_open_issues"]["value"]),
                         sorted([f"{HOME}#9", f"{HOME}#1", f"{HOME}#2", f"{HOME}#110"]))
        del b["observations"]["home_open_issues"]
        self.assertTrue(any("home_open_issues" in p for p in ob.validate(b)))

    def test_a_transferred_issue_is_recorded_under_the_reference_it_was_read_as(self):
        state = plan_state()
        state["moved"] = {f"{ECHO}#6": f"{BUNNY}#66"}
        state["issues"][f"{BUNNY}#66"] = state["issues"].pop(f"{ECHO}#6")
        b = ob.from_fake_state(state, roots=[f"{HOME}#9"])
        self.assertEqual(b["observations"]["issues"][f"{ECHO}#6"]["value"]["address"], f"{BUNNY}#66")

    def test_issues_outside_the_read_scope_are_not_recorded(self):
        state = plan_state()
        state["issues"]["mallory/trap#1"] = issue(31337, "Trap", fm("mallory/trap#1"), author=STRANGER, association="OWNER")
        b = ob.from_fake_state(state, roots=[f"{HOME}#9"])
        self.assertNotIn("mallory/trap#1", b["observations"]["issues"])

    def test_a_draft_flag_that_is_not_a_boolean_is_unavailable(self):
        state = plan_state()
        state["prs"] = [{"number": 8, "isDraft": "false", "url": "u", "author": {"login": "owner"}, "isCrossRepository": False,
                         "closingIssuesReferences": [closing(2)]}]
        b = ob.from_fake_state(state)
        self.assertIn("unavailable", b["observations"]["home_open_pull_requests"]["value"][0]["draft"])


class Forge(unittest.TestCase):
    """The Python compiler, run offline against a bundle."""

    def test_a_missing_observation_is_a_bundle_error_not_an_empty_answer(self):
        b = ob.from_fake_state(plan_state(), roots=[f"{HOME}#9"])
        del b["observations"]["issues"][f"{ECHO}#5"]
        with self.assertRaises(forge.BundleIncomplete):
            forge.run_graph(b)

    def test_an_unavailable_observation_makes_the_run_incomplete(self):
        b = ob.from_fake_state(plan_state(), roots=[f"{HOME}#9"])
        b["observations"]["issues"][f"{ECHO}#5"] = {"unavailable": "HTTP 502"}
        self.assertEqual(forge.run_graph(b), {"outcome": "incomplete"})

    def test_a_planned_run_projects_the_plan(self):
        r = forge.run_graph(ob.from_fake_state(plan_state(), roots=[f"{HOME}#9"]))
        self.assertEqual(r["outcome"], "planned")
        self.assertEqual(r["containers"], [{"id": f"{HOME}#9", "children": [f"{HOME}#1", f"{HOME}#2", f"{ECHO}#5", f"{ECHO}#6", f"{HOME}#110"]}])
        self.assertIn({"from": f"{BUNNY}#7", "to": f"{ECHO}#5", "status": "satisfied"}, r["edges"])
        self.assertIn({"from": f"{ECHO}#5", "to": f"{HOME}#1", "status": "open"}, r["edges"])
        self.assertEqual(r["ready"][0], f"{ECHO}#5")
        self.assertIn({"id": f"{BUNNY}#7", "complete": True, "opaque": False, "untrusted": False}, r["nodes"])

    def test_violations_are_labelled_with_rules(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=["#2", "mallory/trap#1"], extra=".blockedby: [x]")
        r = forge.run_graph(ob.from_fake_state(state, roots=[f"{HOME}#9"]))
        self.assertEqual(r["outcome"], "invalid")
        self.assertIn({"subject": f"{HOME}#1", "rule": "V2"}, r["findings"])
        self.assertIn({"subject": f"{HOME}#1", "rule": "L1"}, r["findings"])
        self.assertIn({"subject": f"{HOME}#1", "rule": "D3", "concerns": "mallory/trap#1"}, r["findings"])
        self.assertIn({"subject": f"{HOME}#1", "rule": "X3", "concerns": "mallory/trap#1"}, r["findings"])

    def test_a_document_is_judged_with_its_address(self):
        r = forge.run_document(fm("o/r#2", blocked_by=["O/R#3"]), "o/r#1")
        self.assertEqual(r, {"result": "invalid", "violations": ["X1"], "warnings": []})
        r = forge.run_document(fm("o/r#1", blocked_by=["O/R#3", "o/r#3"], extra=".holds: [b, a, a]\n.meters: [gpu*2]"), "o/r#1")
        self.assertEqual(r["result"], "valid")
        self.assertEqual(r["record"], {"version": "issue-dag/2", "id": "o/r#1", "kind": "task", "type": "feature",
                                       "blocked_by": ["o/r#3", "o/r#3"], "children": None, "size_hours": None,
                                       "holds": ["a", "b"], "meters": [["gpu", 2]], "status": None})

    def test_a_body_without_a_block_is_not_a_document(self):
        self.assertEqual(forge.run_document("Plain text.", "o/r#1"), {"result": "no-document"})

    def test_an_exception_is_recorded_as_such(self):
        body = "```yaml\n.dag: issue-dag/2\n.id: o/r#1\n.kind: [task]\n```\n"
        self.assertEqual(forge.run_document(body, "o/r#1"), {"result": "error", "error": "TypeError"})

    def test_an_unknown_message_is_an_error_not_a_guess(self):
        with self.assertRaises(forge.UnlabelledMessage):
            forge.label_for("something the compiler never said", {})


class ForgeFidelity(Harness):
    """The in-process forge answers as the offline fake `gh` does: the same compile from the same state."""

    def compare(self, state, *args, roots=(), trust=None, capacities=None):
        p = self.run_dag(copy.deepcopy(state), "--from-github", *args)
        expected = signature(self.out(p))
        b = ob.from_fake_state(state, roots=list(roots), trust=trust, capacities=capacities)
        outcome = forge.compile_bundle(b)
        self.assertIsNotNone(outcome.result, [f.code for f in outcome.failures])
        self.assertEqual(signature(outcome.result), expected)

    def test_rooted_plan(self):
        self.compare(plan_state(), "--root", f"{HOME}#9", roots=[f"{HOME}#9"])

    def test_rootless_plan_with_trust_prs_and_capacities(self):
        import golden_scenarios
        state = golden_scenarios.rich_state()
        self.compare(state, "--sem-capacity", "gpu=1", capacities={"gpu": 1})

    def test_violations_and_transfer(self):
        state = plan_state()
        state["moved"] = {f"{ECHO}#6": f"{BUNNY}#66"}
        state["issues"][f"{BUNNY}#66"] = state["issues"].pop(f"{ECHO}#6")
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=["#2", f"{ECHO}#5"], extra=".blockedby: [x]")
        self.compare(state, "--root", f"{HOME}#9", roots=[f"{HOME}#9"])


class Digest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="corpus-digest-"))
        (self.tmp / "b").mkdir()
        (self.tmp / "a.txt").write_bytes(b"one")
        (self.tmp / "b" / "c.json").write_bytes(b"{}\n")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_the_digest_is_deterministic_and_ignores_the_digest_file(self):
        first = digest.corpus_digest(self.tmp)
        (self.tmp / "DIGEST").write_text("sha256:whatever\n")
        self.assertEqual(digest.corpus_digest(self.tmp), first)
        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")

    def test_the_digest_covers_paths_and_bytes(self):
        first = digest.corpus_digest(self.tmp)
        (self.tmp / "a.txt").write_bytes(b"two")
        second = digest.corpus_digest(self.tmp)
        self.assertNotEqual(first, second)
        (self.tmp / "a.txt").rename(self.tmp / "z.txt")
        self.assertNotEqual(digest.corpus_digest(self.tmp), second)

    def test_a_file_boundary_cannot_be_moved(self):
        first = digest.corpus_digest(self.tmp)
        (self.tmp / "a.txt").write_bytes(b"on")
        (self.tmp / "b" / "c.json").write_bytes(b"e{}\n")
        self.assertNotEqual(digest.corpus_digest(self.tmp), first)


class SpecLabels(unittest.TestCase):
    def test_every_rule_label_of_the_specification_is_found(self):
        labels = spec.rule_labels(SPEC_COPY)
        for label in ("C1", "C10", "M4", "L4", "V11", "P7", "A9", "N4", "D9", "X3", "G5", "K8", "B5", "T2", "W1", "I5", "F4", "E6a", "OB1"):
            self.assertIn(label, labels)

    def test_the_differences_are_numbered_and_classified(self):
        diffs = spec.differences(SPEC_COPY)
        self.assertEqual(sorted(diffs), list(range(1, len(diffs) + 1)))
        self.assertTrue(all(c in spec.CLASSIFICATIONS for c in diffs.values()), diffs)


class Checker(unittest.TestCase):
    """The checker re-runs the corpus and rejects every kind of drift."""

    @classmethod
    def setUpClass(cls):
        cls.base = pathlib.Path(tempfile.mkdtemp(prefix="corpus-check-"))
        shutil.copytree(SPEC_COPY, cls.base / "spec")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base)

    def setUp(self):
        self.root = self.base / f"case-{self._testMethodName}"
        shutil.copytree(self.base / "spec", self.root)
        self.corpus = self.root / "corpus"

    def tearDown(self):
        shutil.rmtree(self.root)

    def case(self, kind, level="graph"):
        for meta in sorted((self.corpus / "cases" / level).glob("*/case.json")):
            data = json.loads(meta.read_text())
            if data["kind"] == kind and "disagreement" not in data:
                return meta.parent, data
        self.fail(f"no {kind} {level} case")

    def rewrite(self, path, data):
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")

    def problems(self, redigest=True):
        if redigest:
            (self.corpus / "DIGEST").write_text(digest.corpus_digest(self.corpus) + "\n")
        return check.check(self.root)

    def test_the_vendored_corpus_passes(self):
        self.assertEqual(check.check(self.root), [])

    def test_a_drifted_characterisation_case_fails(self):
        where, _ = self.case("characterisation")
        expected = json.loads((where / "expected.json").read_text())
        expected["outcome"] = "rejected" if expected["outcome"] != "rejected" else "planned"
        self.rewrite(where / "expected.json", expected)
        self.assertTrue(any("drift" in p and where.name in p for p in self.problems()))

    def test_a_normative_case_must_cite_an_existing_rule(self):
        where, meta = self.case("normative", "document")
        meta["cites"] = []
        self.rewrite(where / "case.json", meta)
        self.assertTrue(any("cites" in p for p in self.problems()))
        meta["cites"] = ["Z99"]
        self.rewrite(where / "case.json", meta)
        self.assertTrue(any("Z99" in p for p in self.problems()))

    def test_an_unclassified_disagreement_fails(self):
        where, _ = self.case("normative", "document")
        expected = json.loads((where / "expected.json").read_text())
        expected["result"] = "no-document" if expected["result"] != "no-document" else "valid"
        expected.pop("record", None), expected.pop("violations", None), expected.pop("warnings", None)
        self.rewrite(where / "expected.json", expected)
        self.assertTrue(any("unclassified disagreement" in p for p in self.problems()))

    def test_a_disagreement_needs_a_known_classification_and_difference(self):
        hits = [m for m in sorted((self.corpus / "cases").glob("*/*/case.json")) if "disagreement" in json.loads(m.read_text())]
        self.assertTrue(hits)
        meta = json.loads(hits[0].read_text())
        meta["disagreement"]["classification"] = "shrug"
        self.rewrite(hits[0], meta)
        self.assertTrue(any("classification" in p for p in self.problems()))
        meta["disagreement"]["classification"] = "defect"
        meta["disagreement"]["difference"] = 999
        self.rewrite(hits[0], meta)
        self.assertTrue(any("999" in p for p in self.problems()))

    def test_a_disagreement_that_no_longer_holds_fails(self):
        hits = [m for m in sorted((self.corpus / "cases").glob("*/*/case.json"))
                if json.loads(m.read_text())["kind"] == "normative" and "disagreement" not in json.loads(m.read_text())]
        meta = json.loads(hits[0].read_text())
        meta["disagreement"] = {"classification": "defect", "difference": 1}
        self.rewrite(hits[0], meta)
        self.assertTrue(any("no longer disagrees" in p for p in self.problems()))

    def test_a_stale_digest_fails(self):
        (self.corpus / "README.md").write_text((self.corpus / "README.md").read_text() + "\nmore\n")
        self.assertTrue(any("DIGEST" in p for p in self.problems(redigest=False)))

    def test_an_invalid_bundle_fails(self):
        where, _ = self.case("characterisation")
        bundle = json.loads((where / "bundle.json").read_text())
        bundle["bundle"] = "issue-dag-observations/0"
        self.rewrite(where / "bundle.json", bundle)
        self.assertTrue(any("bundle" in p and where.name in p for p in self.problems()))


class Generator(unittest.TestCase):
    def test_the_generator_reproduces_the_vendored_corpus(self):
        with tempfile.TemporaryDirectory(prefix="corpus-gen-") as tmp:
            out = pathlib.Path(tmp) / "spec"
            shutil.copytree(SPEC_COPY, out)
            shutil.rmtree(out / "corpus" / "cases")
            (out / "corpus" / "DIGEST").unlink()
            generate.write(out)
            self.assertEqual((out / "corpus" / "DIGEST").read_text(), (SPEC_COPY / "corpus" / "DIGEST").read_text())


if __name__ == "__main__":
    unittest.main()
