"""The output contract (docs/topics/output/README.md; ledger: docs/topics/output/test-plan.md).

Every row of the test plan names the test here that implements it.
"""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import unittest

import golden_scenarios as g
import parley_lines as pl
from test_taskalisk import BUNNY, ECHO, HOME, SCRIPT, STRANGER, Harness, fm, issue, plan_state

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL_IDS = sorted(i for (i, _) in pl.TOOL_SCHEMAS)
OLD_TO_NEW_EXIT = {0: 0, 1: 2, 2: 2}


class Golden(unittest.TestCase):
    """OUT-02: the lines carry everything the 1.x document did."""

    def run_new(self, name):
        tmp = tempfile.mkdtemp(prefix="taskalisk-golden-")
        g.prepare(tmp)
        p = g.run_scenario(SCRIPT, name, tmp, env_extra={"XDG_STATE_HOME": str(pathlib.Path(tmp) / "state")})
        out, err = pl.parse(p.stdout, "stdout"), pl.parse(p.stderr, "stderr")
        receipt = pl.receipt_lines(out)
        self.assertEqual(pl.problems(out + err + receipt), [], name)
        return p, out, err, tmp

    def test_every_scenario_reconstructs_the_old_document(self):
        for name in g.SCENARIOS:
            with self.subTest(name):
                fixture = g.load(name)
                p, out, err, tmp = self.run_new(name)
                self.assertEqual(p.returncode, OLD_TO_NEW_EXIT[fixture["exit"]], p.stderr[-800:])
                if "stdout_text" in fixture:
                    fmt = "roadmap" if "--emit-roadmap" in fixture["args"] else "mermaid"
                    self.assertEqual(pl.rendering(out, fmt) + "\n", fixture["stdout_text"])
                    continue
                self.assertEqual(g.normalise(pl.reconstruct(out, err), tmp), fixture["stdout"])

    def test_artifact_hash_is_the_old_one(self):
        for name in g.SCENARIOS:
            fixture = g.load(name)
            old = (fixture.get("stdout") or {}).get("meta", {}).get("artifact_hash")
            if old is None:
                continue
            with self.subTest(name):
                _, out, _, _ = self.run_new(name)
                self.assertEqual(pl.one(out, "taskalisk.plan")["artifact_hash"], old)


class Order(Harness):
    def test_plan_then_frontier_then_batch_then_the_rest(self):
        """OUT-03."""
        p = self.run_dag(g.rich_state(), "--from-github", "--sem-capacity", "gpu=1")
        out, _ = self.streams(p)
        events = [l["event"] for l in out]
        self.assertEqual(events[0], "run")
        self.assertEqual(events[1], "plan")
        n = len(pl.of(out, "taskalisk.frontier_node"))
        self.assertGreater(n, 1)
        self.assertEqual(events[2:2 + n], ["frontier_node"] * n)
        self.assertEqual(events[2 + n], "batch")
        self.assertEqual(events[-1], "end")
        self.assertEqual([l["rank"] for l in pl.of(out, "taskalisk.frontier_node")], list(range(1, n + 1)))
        self.assertEqual([l["id"] for l in pl.of(out, "taskalisk.frontier_node")], pl.one(out, "taskalisk.plan")["frontier"])

    def test_edge_edit_comes_first_in_an_edit(self):
        p = self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9", "--add-edge", f"{ECHO}#6->{HOME}#2")
        events = [l["event"] for l in self.streams(p)[0]]
        self.assertEqual(events[:3], ["run", "edge_edit", "plan"])


class Score(Harness):
    def test_frontier_node_states_its_score_and_each_term(self):
        """OUT-04."""
        p = self.run_dag(g.rich_state(), "--from-github", "--sem-capacity", "gpu=1")
        nodes = pl.of(self.streams(p)[0], "taskalisk.frontier_node")
        seen = set()
        for n in nodes:
            terms = n["score"]["terms"]
            self.assertEqual(set(terms), {"in_flight", "parked", "descendants", "critical_path_depth", "out_degree"})
            for name, t in terms.items():
                self.assertEqual(t["points"], t["value"] * t["weight"], name)
                if t["value"]:
                    seen.add(name)
            self.assertEqual(n["score"]["total"], sum(t["points"] for t in terms.values()))
            self.assertEqual(n["score"]["total"], n["priority_score"])
        self.assertEqual({t: w for t, w in ((k, v["weight"]) for k, v in nodes[0]["score"]["terms"].items())},
                         {"in_flight": 1000, "parked": 500, "descendants": 100, "critical_path_depth": 10, "out_degree": 1})
        self.assertTrue({"in_flight", "descendants", "critical_path_depth", "out_degree"} <= seen, seen)

    def test_parked_term(self):
        state = {"home": HOME, "blocked_by": {}, "issues": {f"{HOME}#1": issue(101, "Parked", fm(f"{HOME}#1", extra=".status: parked"))}}
        node = pl.one(self.streams(self.run_dag(state, "--from-github"))[0], "taskalisk.frontier_node")
        self.assertEqual(node["score"]["terms"]["parked"], {"value": 1, "weight": 500, "points": 500})


class Errors(Harness):
    """OUT-05: every failure is a typed parley.error, exit 2."""

    def assert_error(self, p, code, status=2):
        out, err = self.streams(p)
        self.assertEqual(p.returncode, status, p.stderr[-800:])
        self.assertIn(code, [e["code"] for e in pl.of(err, "parley.error")], p.stderr[-800:])
        self.assertEqual(out[-1]["event"], "end")
        self.assertEqual(out[-1]["status"], status)
        return out, err

    def test_gh_failure(self):
        state = plan_state()
        state["fail_graphql"] = True
        _, err = self.assert_error(self.run_dag(state, "--from-github"), "gh.command_failed")
        e = pl.one(err, "parley.error")
        self.assertTrue(e["retryable"])
        self.assertEqual(e["detail"]["phase"], "discovery")

    def test_list_limit_reached(self):
        state = {"home": HOME, "blocked_by": {}, "issues": {f"{HOME}#{n}": issue(n, f"t{n}", fm(f"{HOME}#{n}")) for n in range(1, 1001)}}
        self.assert_error(self.run_dag(state, "--from-github"), "gh.list_limit_reached")
        self.assertFalse(any(c[:2] == ["api", "graphql"] for c in self.calls()))

    def test_invalid_frontmatter(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", extra=".bogus: 1")
        out, _ = self.assert_error(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"), "frontmatter.invalid")
        plan = pl.one(out, "taskalisk.plan")
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["error_codes"], ["frontmatter.invalid"])

    def test_cycle(self):
        spec = self.tmp / "dag.json"
        spec.write_text(json.dumps(g.DAG_CYCLE))
        out, _ = self.assert_error(self.run_dag(plan_state(), "--verify-dag", str(spec)), "graph.cycle")
        self.assertEqual(pl.one(out, "taskalisk.plan")["outcome"], "cycle")
        self.assertEqual(sorted(f["subject"] for f in pl.findings(out, "graph.cyclic_node")), [f"{HOME}#1", f"{HOME}#2"])

    def test_unresolved_prerequisite(self):
        spec = self.tmp / "dag.json"
        spec.write_text(json.dumps({"nodes": {"a": {"title": "a", "depends_on": ["ghost"]}}}))
        out, _ = self.assert_error(self.run_dag(plan_state(), "--verify-dag", str(spec)), "graph.unresolved_prerequisites")
        self.assertEqual(pl.details(out, "prerequisite.unknown"), [{"node": "a", "unknown_prerequisite": "ghost"}])

    def test_refused_edit(self):
        state = plan_state()
        state["issues"][f"{HOME}#2"].update(author=STRANGER, association="NONE")
        self.assert_error(self.run_dag(state, "--from-github", "--add-edge", f"{ECHO}#6->{HOME}#2"), "edge.child_untrusted")

    def test_failed_write(self):
        state = plan_state()
        state["patch_fail"] = True
        _, err = self.assert_error(self.run_dag(state, "--from-github", "--add-edge", f"{ECHO}#6->{HOME}#2"), "gh.mutation_failed")
        self.assertEqual(pl.one(err, "parley.error")["detail"]["phase"], "edge_edit")

    def test_mutation_failure_restores_the_body(self):
        state = plan_state()
        state["fail_graphql_for"] = [f"{HOME}#1"]
        before = state["issues"][f"{HOME}#2"]["body"]
        out, _ = self.assert_error(self.run_dag(state, "--from-github", "--add-edge", f"{ECHO}#6->{HOME}#2"), "gh.command_failed")
        self.assertTrue(pl.one(out, "taskalisk.edge_edit")["rolled_back"])
        self.assertEqual(self.current()["issues"][f"{HOME}#2"]["body"], before)

    def test_unreadable_dag_spec(self):
        self.assert_error(self.run_dag(plan_state(), "--verify-dag", str(self.tmp / "missing.json")), "dag_spec.unreadable")

    def test_malformed_dag_spec_field(self):
        spec = self.tmp / "dag.json"
        spec.write_text(json.dumps({"nodes": {"a": {"title": 5}}}))
        self.assert_error(self.run_dag(plan_state(), "--verify-dag", str(spec)), "dag_spec.invalid")

    def test_cycle_from_an_added_edge_is_restored(self):
        """OUT-15."""
        state = plan_state()
        before = state["issues"][f"{ECHO}#5"]["body"]
        out, _ = self.assert_error(self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--add-edge", f"{HOME}#2->{ECHO}#5"), "graph.cycle")
        self.assertTrue(pl.one(out, "taskalisk.edge_edit")["rolled_back"])
        self.assertEqual(self.current()["issues"][f"{ECHO}#5"]["body"], before)


class Usage(Harness):
    def test_usage_errors_are_startup_failures(self):
        """OUT-06."""
        for args in (["--from-github", "--add-edge", f"{HOME}#1->{HOME}#2", "--remove-edge", f"{HOME}#1->{HOME}#2"],
                     ["--from-github", "--sem-capacity", "gpu=0"], ["--emit-roadmap"], ["--from-github", "--frobnicate"],
                     ["--from-github", "--add-edge", f"{HOME}#1-{HOME}#2"], ["--from-github", "--add-edge", f"{HOME}#1->{HOME}#1"],
                     ["--from-github", "--root", "#9"], ["--from-github", "--root", "geordi"]):
            with self.subTest(args):
                p = self.run_dag(plan_state(), *args)
                self.assertEqual(p.returncode, 3, p.stderr)
                self.assertEqual(p.stdout, "")
                err = pl.parse(p.stderr, "stderr")
                self.assertEqual([l["event"] for l in err], ["startup.failed"])
                self.assertEqual(err[0]["code"], "startup.arguments_invalid")
                self.assertEqual(pl.problems(err), [])
                self.assertEqual(self.calls(), [])
                self.assertFalse((self.tmp / ".parley" / "receipts").exists() and any((self.tmp / ".parley" / "receipts").iterdir()))


class Discovery(Harness):
    def test_schema_lists_every_command_and_schema(self):
        """OUT-07."""
        p = self.run_dag(plan_state(), "--schema")
        self.assertEqual(p.returncode, 0, p.stderr)
        out, err = self.streams(p)
        self.assertEqual(err, [])
        self.assertEqual(sorted(c["name"] for c in pl.of(out, "parley.command")), ["edit", "inventory", "plan", "verify"])
        ids = {s["id"] for s in pl.of(out, "parley.schema")}
        self.assertTrue(set(TOOL_IDS) <= ids, set(TOOL_IDS) - ids)
        self.assertIn("parley.error", ids)
        for s in pl.of(out, "parley.schema"):
            if s["id"].startswith("taskalisk."):
                self.assertEqual(s["schema"], pl.TOOL_SCHEMAS[(s["id"], s["version"])])
        self.assertEqual(self.calls(), [])

    def test_help_describes_one_command(self):
        for args in (["plan", "--help"], ["--from-github", "--help"]):
            with self.subTest(args):
                p = self.run_dag(plan_state(), *args)
                self.assertEqual(p.returncode, 0, p.stderr)
                out, _ = self.streams(p)
                commands = pl.of(out, "parley.command")
                self.assertEqual([c["name"] for c in commands], ["plan"])
                self.assertEqual(commands[0]["secrets"], ["GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"])
                ids = {s["id"] for s in pl.of(out, "parley.schema")}
                self.assertIn("taskalisk.frontier_node", ids)
                self.assertIn("parley.error", ids)
                self.assertIn("parley.startup.failed", ids)
                self.assertNotIn("taskalisk.edge_edit", ids)

    def test_only_edit_declares_a_write(self):
        out, _ = self.streams(self.run_dag(plan_state(), "--schema"))
        writes = {c["name"]: c["effects"]["writes"] for c in pl.of(out, "parley.command")}
        self.assertEqual([n for n, w in writes.items() if w], ["edit"])


CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f  ‪-‮⁦-⁩]")


class Human(Harness):
    def receipt_of_only_run(self):
        receipts = sorted((self.tmp / ".parley" / "receipts").glob("*.jsonl"))
        self.assertEqual(len(receipts), 1)
        return pl.parse(receipts[0].read_text(), "receipt")

    def test_human_prints_a_ranked_table_and_findings(self):
        """OUT-08."""
        p = self.run_dag(g.rich_state(), "--from-github", "--sem-capacity", "gpu=1", "--human")
        self.assertEqual(p.returncode, 0, p.stderr)
        for line in p.stdout.splitlines():
            with self.assertRaises(ValueError, msg=line):
                json.loads(line)
        self.assertIn("rank", p.stdout)
        self.assertIn(f"{HOME}#3", p.stdout)
        self.assertIn("issue.untrusted", p.stdout)
        self.assertNotIn("\n\n\n", p.stdout)
        receipt = self.receipt_of_only_run()
        self.assertEqual(pl.problems(receipt), [])
        self.assertEqual(receipt[-1]["event"], "end")
        self.assertTrue(pl.of(receipt, "taskalisk.frontier_node"))

    def test_human_errors_are_prose(self):
        state = plan_state()
        state["fail_graphql"] = True
        p = self.run_dag(state, "--from-github", "--human")
        self.assertEqual(p.returncode, 2)
        self.assertIn("gh.command_failed", p.stderr)
        self.assertFalse(any(l.startswith("{") for l in p.stderr.splitlines()))


class SinceLast(Harness):
    def test_no_previous_receipt_is_a_finding(self):
        p = self.run_dag(plan_state(), "--from-github", "--since-last")
        self.assertEqual(p.returncode, 0, p.stderr)
        out, _ = self.streams(p)
        self.assertEqual(len(pl.findings(out, "since_last.no_previous")), 1)
        self.assertEqual(pl.one(out, "taskalisk.plan")["since_last"], {"compared_with": None, "changes": 0})

    def test_promotion_after_a_blocker_closes(self):
        """OUT-09: the change is read from the two receipts alone."""
        state = plan_state()
        first = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        self.assertEqual(first.returncode, 0, first.stderr)
        state["issues"][f"{ECHO}#5"]["state"] = "closed"
        state["issues"][f"{ECHO}#5"]["state_reason"] = "completed"
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        self.log.write_text("")
        self.run_dag(state, "--from-github", "--root", f"{HOME}#9", cwd=elsewhere)  # the same run without --since-last, receipts kept apart
        plain_calls = self.calls()
        self.log.write_text("")
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--since-last")
        self.assertEqual(self.calls(), plain_calls, "--since-last must read nothing from GitHub")
        out, _ = self.streams(p)
        changes = {(c["change"], c["id"]) for c in pl.of(out, "taskalisk.frontier_change")}
        self.assertIn(("promoted", f"{HOME}#1"), changes)
        self.assertIn(("promoted", f"{ECHO}#6"), changes)
        self.assertIn(("closed", f"{ECHO}#5"), changes)
        previous_run = pl.parse(first.stdout, "stdout")[0]["run"]
        self.assertEqual({c["since_run"] for c in pl.of(out, "taskalisk.frontier_change")}, {previous_run})
        self.assertEqual(pl.one(out, "taskalisk.plan")["since_last"], {"compared_with": previous_run, "changes": len(changes)})

    def test_a_different_question_is_not_compared(self):
        self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9")
        p = self.run_dag(plan_state(), "--from-github", "--since-last")
        self.assertEqual(len(pl.findings(self.streams(p)[0], "since_last.no_previous")), 1)

    def test_newly_blocked(self):
        state = plan_state()
        self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        state["issues"][f"{ECHO}#5"]["body"] = fm(f"{ECHO}#5", blocked_by=[f"{BUNNY}#7", f"{BUNNY}#110"])
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--since-last")
        changes = {(c["change"], c["id"]) for c in pl.of(self.streams(p)[0], "taskalisk.frontier_change")}
        self.assertIn(("newly_blocked", f"{ECHO}#5"), changes)


SECRET = "tok_SUPERSECRET_9f3a1"
URL_SECRET = "URLSECRET_77c2"


class Secrets(Harness):
    def test_no_declared_secret_reaches_any_stream_or_the_receipt(self):
        """OUT-10."""
        state = plan_state()
        state["issues_list_fail_message"] = ("gh: token {GH_TOKEN} rejected while fetching "
                                             f"https://x-access-token:{URL_SECRET}@github.com/{HOME}.git")
        p = self.run_dag(state, "--from-github", env=self.env(GH_TOKEN=SECRET))
        self.assertEqual(p.returncode, 2)
        text = self.text_everywhere(p)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(URL_SECRET, text)
        out, _ = self.streams(p)
        receipt = pl.receipt_lines(out)
        self.assertEqual(receipt[0]["redacted"]["env"], ["GH_TOKEN"])
        self.assertTrue(out[-1]["redacted"])


MARKS = ("MARK_TITLE_SEED", "MARK_BODY_SEED", "MARK_TITLE_REF", "MARK_BODY_REF")


class Untrusted(Harness):
    def test_nothing_an_untrusted_author_wrote_reaches_any_line(self):
        """OUT-11."""
        state = plan_state()
        state["issues"][f"{HOME}#77"] = issue(177, "MARK_TITLE_SEED", fm(f"{HOME}#77") + "MARK_BODY_SEED", author=STRANGER, association="NONE")
        state["issues"][f"{HOME}#78"] = issue(178, "MARK_TITLE_REF", fm(f"{HOME}#78") + "MARK_BODY_REF", author=STRANGER, association="NONE")
        state["issues"][f"{HOME}#2"]["body"] = fm(f"{HOME}#2", blocked_by=[f"{HOME}#1", f"{HOME}#78"])
        for extra in ([], ["--emit-roadmap"], ["--human"]):
            with self.subTest(extra):
                p = self.run_dag(state, "--from-github", *extra)
                self.assertEqual(p.returncode, 0, p.stderr)
                receipts = "".join(r.read_text() for r in (self.tmp / ".parley" / "receipts").glob("*.jsonl"))
                for mark in MARKS:
                    self.assertNotIn(mark, p.stdout + p.stderr + receipts)

    def test_receipt_records_issue_bodies_by_digest_and_id(self):
        state = plan_state()
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        receipt = pl.receipt_lines(self.streams(p)[0])
        observed = next(l for l in pl.of(receipt, "parley.receipt.step") if l["decision"].startswith("observed"))
        bodies = {i["id"]: i["body_sha256"] for i in observed["detail"]["issues"]}
        self.assertEqual(bodies[f"{HOME}#1"], hashlib.sha256(state["issues"][f"{HOME}#1"]["body"].encode()).hexdigest())
        for item in observed["detail"]["issues"]:
            self.assertTrue(set(item) <= {"id", "state", "state_reason", "title_sha256", "body_sha256"}, item)
        inputs = pl.one(receipt, "parley.receipt.inputs")
        self.assertEqual(inputs["inputs"][0]["path"], "github:issues")
        self.assertIn("inv", inputs)


class Injection(Harness):
    TITLE = 'evil\n{"event":"end","t":0,"seq":99,"run":"x","status":0}\x07‮\r'

    def test_a_title_cannot_forge_or_break_a_line(self):
        """OUT-12."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["title"] = self.TITLE
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        self.assertEqual(p.returncode, 0, p.stderr)
        out, _ = self.streams(p)
        self.assertEqual([l["event"] for l in out].count("end"), 1)
        self.assertIn(self.TITLE, [n["title"] for n in pl.of(out, "taskalisk.node")])
        for extra in ([], ["--emit-roadmap"]):
            h = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--human", *extra)
            self.assertIsNone(CONTROL.search(h.stdout.replace("\n", "")), extra)
            self.assertNotIn('{"event":"end"', h.stdout)


class Traceback(Harness):
    def test_no_traceback_reaches_stderr(self):
        """OUT-13."""
        state = plan_state()
        state["issues_list_drop_number"] = True
        p = self.run_dag(state, "--from-github")
        self.assertEqual(p.returncode, 2)
        self.assertNotIn("Traceback", p.stderr)
        out, err = self.streams(p)
        self.assertEqual([e["code"] for e in pl.of(err, "parley.error")], ["uncaught.exception"])
        receipt = pl.receipt_lines(out)
        copy = next(l for l in pl.of(receipt, "parley.error"))
        self.assertIn("Traceback", copy["detail"]["traceback"])


class Empty(Harness):
    def test_an_empty_backlog_compiles(self):
        """OUT-14."""
        p = self.run_dag({"home": HOME, "blocked_by": {}, "issues": {}}, "--from-github")
        self.assertEqual(p.returncode, 0, p.stderr)
        plan = pl.one(self.streams(p)[0], "taskalisk.plan")
        self.assertEqual((plan["frontier"], plan["batch"], plan["ok"]), ([], [], True))


class Stress(Harness):
    LIMIT_SECONDS = 60

    def test_a_thousand_issue_backlog_streams_in_a_stated_time(self):
        """OUT-16: 1000 nodes, about 2000 edges, within LIMIT_SECONDS; no line over 65,536 bytes."""
        nodes = {}
        for n in range(1, 1001):
            deps = [f"{HOME}#{m}" for m in (n - 1, n - 7) if m >= 1]
            nodes[f"{HOME}#{n}"] = {"title": f"Task {n}", "depends_on": deps}
        spec = self.tmp / "dag.json"
        spec.write_text(json.dumps({"nodes": nodes}))
        start = time.monotonic()
        p = self.run_dag(plan_state(), "--verify-dag", str(spec))
        elapsed = time.monotonic() - start
        self.assertEqual(p.returncode, 0, p.stderr[-500:])
        self.assertLess(elapsed, self.LIMIT_SECONDS)
        out, _ = self.streams(p)
        self.assertEqual(len(pl.of(out, "taskalisk.frontier_node")) + len(pl.of(out, "taskalisk.node")), 1000)
        self.assertLessEqual(max(len(l.encode()) for l in p.stdout.splitlines()), 65536)


class Paths(Harness):
    def test_the_home_directory_is_shown_as_tilde(self):
        """OUT-18."""
        state = plan_state()
        state["issues_list_fail_message"] = "gh: cannot read {HOME}/private/config.yml"
        p = self.run_dag(state, "--from-github")
        self.assertEqual(p.returncode, 2)
        self.assertIn("~/private/config.yml", p.stderr)
        self.assertNotIn(os.path.expanduser("~") + "/private", p.stdout + p.stderr)


class DryRun(Harness):
    def test_dry_run_edit_writes_nothing(self):
        """OUT-22."""
        state = plan_state()
        before = state["issues"][f"{HOME}#2"]["body"]
        p = self.run_dag(state, "--from-github", "--add-edge", f"{ECHO}#6->{HOME}#2", "--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr)
        edit = pl.one(self.streams(p)[0], "taskalisk.edge_edit")
        self.assertTrue(edit["dry_run"])
        self.assertTrue(edit["changed"])
        self.assertFalse(any("PATCH" in c for c in self.calls()))
        self.assertEqual(self.current()["issues"][f"{HOME}#2"]["body"], before)


class Vendored(unittest.TestCase):
    """OUT-17: the vendored writer is the pinned file, byte for byte."""
    SCRIPTS = ROOT / "skills" / "taskalisk" / "scripts"

    def test_copy_matches_its_pin(self):
        pin = json.loads((self.SCRIPTS / "parley_emit.pin.json").read_text())
        data = (self.SCRIPTS / "parley_emit.py").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), pin["sha256"])
        self.assertEqual(len(data), pin["bytes"])
        info = json.loads(subprocess.run([sys.executable, str(self.SCRIPTS / "parley_emit.py"), "--vendor-info"],
                                         capture_output=True, text=True, check=True).stdout)
        self.assertEqual((info["sha256"], info["version"], info["spec"], info["schemas"]["commit"]),
                         (pin["sha256"], pin["version"], pin["spec"], pin["schemas_commit"]))

    def test_every_tool_schema_is_inside_the_checker_subset(self):
        for key, doc in pl.TOOL_SCHEMAS.items():
            self.assertIsNone(pl.pe.schema_subset_gap(doc), key)
            self.assertEqual(doc["$id"], f"https://flyingrobots.dev/taskalisk/schemas/{key[0]}/{key[1]}")


DOCTOR = pathlib.Path(__file__).resolve().parent / "fixtures" / "doctor"


class DoctorFixtures(unittest.TestCase):
    """OUT-19: the runs the doctor passed stay valid offline."""

    def test_every_captured_line_validates(self):
        runs = sorted(p for p in DOCTOR.iterdir() if p.is_dir())
        self.assertGreaterEqual({r.name for r in runs}, {"plan", "inventory", "edit", "gh-failure", "help", "schema", "human"})
        for run in runs:
            with self.subTest(run.name):
                lines = []
                for stream in ("stdout", "stderr", "receipt"):
                    path = run / f"{stream}.jsonl"
                    if run.name == "human" and stream != "receipt":
                        continue  # prose by request (spec 1.1); its receipt is the record the doctor checked
                    if path.exists():
                        lines += pl.parse(path.read_text(), stream)
                self.assertTrue(lines)
                self.assertEqual(pl.problems(lines), [])


class SkillRecipe(unittest.TestCase):
    def test_the_ranked_frontier_recipe_works(self):
        """OUT-21: the python recipe in SKILL.md, run over a captured plan."""
        skill = (ROOT / "skills" / "taskalisk" / "SKILL.md").read_text()
        recipe = re.search(r"<!-- recipe: ranked-frontier -->\s*```python\n(.*?)```", skill, re.S)
        self.assertIsNotNone(recipe, "SKILL.md lost its ranked-frontier recipe")
        stdout = (DOCTOR / "plan" / "stdout.jsonl").read_text()
        p = subprocess.run([sys.executable, "-c", recipe.group(1)], input=stdout, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        plan = pl.one(pl.parse(stdout, "stdout"), "taskalisk.plan")
        self.assertEqual([l.split()[1] for l in p.stdout.splitlines()], plan["frontier"])


if __name__ == "__main__":
    unittest.main()
