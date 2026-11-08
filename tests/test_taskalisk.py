"""Offline tests for taskalisk.py (frontmatter model issue-dag/1).

Run: python3 -m unittest discover -s tests
"""
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "taskalisk" / "scripts" / "taskalisk.py"
FAKE_GH = pathlib.Path(__file__).resolve().parent / "fake_gh.py"
HOME = "flyingrobots/geordi"
ECHO = "flyingrobots/echo"
BUNNY = "flyingrobots/bunny"


def fm(id_, kind="task", type_="feature", blocked_by=(), children=None, extra=""):
    lines = [".dag: issue-dag/2", f".id: {id_}", f".kind: {kind}"]
    if kind == "task":
        lines += [f".type: {type_}", ".blocked_by: [" + ", ".join(blocked_by) + "]"]
    if children is not None:
        lines.append(".children: [" + ", ".join(children) + "]")
    if extra:
        lines.append(extra)
    lines.append("area: notes are free")
    return "```yaml\n" + "\n".join(lines) + "\n```\n\n# Feature\n\nBody text.\n"


def issue(i, title, body, state="open", reason=None, author=None, association=None, editors=None):
    out = {"id": i, "title": title, "state": state, "labels": [], "body": body, "state_reason": reason}
    if author is not None:
        out["author"] = author
    if association is not None:
        out["association"] = association
    if editors is not None:
        out["editors"] = editors
    return out


def closing(number, slug=HOME):
    owner, name = slug.split("/")
    return {"number": number, "repository": {"name": name, "owner": {"login": owner}}}


STRANGER = "mallory"


def plan_state():
    """Home roadmap #9 with children in three repositories; echo#6 blocks nothing at home."""
    return {"home": HOME, "blocked_by": {},
            "issues": {
                f"{HOME}#9": issue(109, "Roadmap", fm(f"{HOME}#9", kind="container", children=[f"{HOME}#1", f"{HOME}#2", f"{ECHO}#5", f"{ECHO}#6", f"{HOME}#110"])),
                f"{HOME}#1": issue(101, "Home one", fm(f"{HOME}#1", blocked_by=[f"{ECHO}#5"])),
                f"{HOME}#2": issue(102, "Home two", fm(f"{HOME}#2", blocked_by=[f"{HOME}#1"])),
                f"{HOME}#110": issue(110, "Home 110", fm(f"{HOME}#110", blocked_by=[f"{BUNNY}#110"])),
                f"{ECHO}#5": issue(5005, "Echo five", fm(f"{ECHO}#5", blocked_by=[f"{BUNNY}#7"])),
                f"{ECHO}#6": issue(5006, "Echo six", fm(f"{ECHO}#6", blocked_by=[f"{ECHO}#5"])),
                f"{BUNNY}#110": issue(9110, "Bunny 110, no frontmatter", "Plain body."),
                f"{BUNNY}#7": issue(9007, "Bunny seven, closed", fm(f"{BUNNY}#7"), state="closed", reason="completed"),
            }}


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="taskalisk-test-"))
        self.bin = self.tmp / "bin"; self.bin.mkdir()
        (self.bin / "gh").write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE_GH} \"$@\"\n")
        (self.bin / "gh").chmod(0o755)
        self.repo = self.tmp / "repo"; self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        self.state = self.tmp / "state.json"
        self.log = self.tmp / "gh.log"; self.log.write_text("")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_dag(self, state, *args):
        self.state.write_text(json.dumps(state))
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", FAKE_GH_STATE=str(self.state), FAKE_GH_LOG=str(self.log))
        return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(self.repo), *args], capture_output=True, text=True, env=env)

    def current(self):
        return json.loads(self.state.read_text())

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]

    def out(self, p):
        try:
            return json.loads(p.stdout)
        except json.JSONDecodeError:
            self.fail(f"not JSON (exit {p.returncode}): {p.stdout[:400]} {p.stderr[:400]}")

    @staticmethod
    def ids(r):
        return sorted(n["id"] for items in r["waves"].values() for n in items)

    @staticmethod
    def node(r, nid):
        return next(n for items in r["waves"].values() for n in items if n["id"] == nid)


class Parsing(Harness):
    def test_verify_dag_spec_still_works(self):
        spec = self.tmp / "dag.json"
        spec.write_text(json.dumps({"nodes": {f"{HOME}#1": {"title": "a"}, f"{HOME}#2": {"title": "b", "depends_on": [f"{HOME}#1"]}}}))
        p = subprocess.run([sys.executable, str(SCRIPT), "--verify-dag", str(spec)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.out(p)["metrics"]["critical_path"], [f"{HOME}#1", f"{HOME}#2"])


class Discovery(Harness):
    def test_cross_repo_closure_from_frontmatter(self):
        p = self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertEqual(self.ids(r), [f"{BUNNY}#110", f"{ECHO}#5", f"{ECHO}#6", f"{HOME}#1", f"{HOME}#110", f"{HOME}#2"])

    def test_other_repo_card_that_blocks_nothing_at_home_is_found_through_children(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertEqual(self.node(r, f"{ECHO}#6")["open_parents"], [f"{ECHO}#5"])

    def test_relative_refs_resolve_in_the_holding_repository(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{ECHO}#6", self.node(r, f"{ECHO}#5")["directly_unlocks"])

    def test_same_number_in_two_repositories_stays_two_nodes(self):
        ids = self.ids(self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9")))
        self.assertIn(f"{HOME}#110", ids)
        self.assertIn(f"{BUNNY}#110", ids)

    def test_closed_issue_is_a_completed_parent(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertEqual(self.node(r, f"{ECHO}#5")["completed_parents"], [f"{BUNNY}#7"])
        self.assertEqual(r["metrics"]["critical_path"], [f"{ECHO}#5", f"{HOME}#1", f"{HOME}#2"])

    def test_referenced_issue_without_frontmatter_is_an_opaque_blocker(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertEqual([o["id"] for o in r["source"]["opaque_nodes"]], [f"{BUNNY}#110"])
        self.assertNotIn(f"{BUNNY}#110", [b["id"] for b in r["conflict_free_frontier_batch"]])
        self.assertEqual(self.node(r, f"{HOME}#110")["open_parents"], [f"{BUNNY}#110"])

    def test_containers_are_excluded_and_reported(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertNotIn(f"{HOME}#9", self.ids(r))
        self.assertEqual([c["id"] for c in r["source"]["containers_excluded"]], [f"{HOME}#9"])

    def test_home_issue_without_frontmatter_is_listed_not_a_node(self):
        state = plan_state()
        state["issues"][f"{HOME}#40"] = issue(140, "Legacy", "No frontmatter here.")
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual([u["id"] for u in r["source"]["unmodeled_open_issues"]], [f"{HOME}#40"])
        self.assertNotIn(f"{HOME}#40", self.ids(r))

    def test_labels_are_ignored(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["labels"] = ["type:goalpost", "milestone", "lock:docs/"]
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{HOME}#1", self.ids(r))
        self.assertEqual(self.node(r, f"{HOME}#1")["holds"], [])


class Validation(Harness):
    def assert_violation(self, body, needle):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = body
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        r = self.out(p)
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(any(needle in v for v in r["frontmatter"]["violations"].get(f"{HOME}#1", [])), r["frontmatter"])

    def test_unknown_dot_key_fails(self):
        self.assert_violation(fm(f"{HOME}#1", extra=f".blockedby: [{HOME}#2]"), "unknown key .blockedby")

    def test_copied_frontmatter_with_wrong_id_fails(self):
        self.assert_violation(fm(f"{HOME}#2", blocked_by=[f"{ECHO}#5"]), "does not name this issue")

    def test_task_without_blocked_by_fails(self):
        self.assert_violation(f"```yaml\n.dag: issue-dag/2\n.id: {HOME}#1\n.kind: task\n.type: feature\n```\n", "needs .blocked_by")

    def test_container_as_blocker_fails(self):
        self.assert_violation(fm(f"{HOME}#1", blocked_by=[f"{HOME}#9"]), f"names container {HOME}#9")

    def test_unparseable_line_fails(self):
        self.assert_violation(fm(f"{HOME}#1", extra="  nested:\n    - x"), "not 'key: value'")

    def test_large_size_is_a_warning_only(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=[f"{ECHO}#5"], extra=".size_hours: 12")
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn(f"{HOME}#1", self.out(p)["frontmatter"]["warnings"])


class QualifiedReferences(Harness):
    def run_with(self, body_for_1):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = body_for_1
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        return p, self.out(p)

    def test_bare_blocker_number_is_invalid(self):
        p, r = self.run_with(fm(f"{HOME}#1", blocked_by=["#2"]))
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(any("bare numbers are not allowed" in v for v in r["frontmatter"]["violations"][f"{HOME}#1"]))

    def test_bare_id_is_invalid(self):
        p, r = self.run_with(fm("#1", blocked_by=[f"{ECHO}#5"]))
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(any("must be owner/repo#N" in v for v in r["frontmatter"]["violations"][f"{HOME}#1"]))

    def test_retired_schema_is_invalid(self):
        p, r = self.run_with(fm(f"{HOME}#1", blocked_by=[f"{ECHO}#5"]).replace("issue-dag/2", "issue-dag/1"))
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(any("retired" in v for v in r["frontmatter"]["violations"][f"{HOME}#1"]))

    def test_bare_cli_references_are_rejected(self):
        for args in (["--add-edge", f"#5->{HOME}#2"], ["--root", "#9"]):
            p = self.run_dag(plan_state(), "--from-github", *args)
            self.assertNotEqual(p.returncode, 0, args)

    def test_transferred_reference_is_reported(self):
        state = plan_state()
        state["moved"] = {f"{ECHO}#6": f"{BUNNY}#66"}
        state["issues"][f"{BUNNY}#66"] = state["issues"].pop(f"{ECHO}#6")
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        r = self.out(p)
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(any(f"{ECHO}#6 moved to {BUNNY}#66" in v for v in r["frontmatter"]["violations"][f"{HOME}#9"]))

    def test_output_ids_are_always_qualified(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertTrue(all("/" in i.split("#")[0] for i in self.ids(r)))


class Resources(Harness):
    def frontier_state(self, extra_a, extra_b):
        return {"home": HOME, "blocked_by": {}, "issues": {
            f"{HOME}#1": issue(101, "A", fm(f"{HOME}#1", extra=extra_a)),
            f"{HOME}#2": issue(102, "B", fm(f"{HOME}#2", extra=extra_b))}}

    def batch(self, state, *args):
        return [b["id"] for b in self.out(self.run_dag(state, "--from-github", *args))["conflict_free_frontier_batch"]]

    def test_no_resources_means_full_parallelism(self):
        self.assertEqual(sorted(self.batch(self.frontier_state("", ""))), [f"{HOME}#1", f"{HOME}#2"])

    def test_overlapping_holds_conflict(self):
        self.assertEqual(len(self.batch(self.frontier_state(".holds: [host/docker/w/]", ".holds: [host/docker/w/cache]"))), 1)

    def test_unknown_semaphore_capacity_is_exclusive(self):
        state = self.frontier_state(".meters: [gpu]", ".meters: [gpu]")
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(len(r["conflict_free_frontier_batch"]), 1)
        self.assertEqual(r["semaphores_with_unknown_capacity_treated_as_1"], ["gpu"])

    def test_declared_semaphore_capacity_allows_parallel_slots(self):
        state = self.frontier_state(".meters: [gpu]", ".meters: [gpu]")
        self.assertEqual(len(self.batch(state, "--sem-capacity", "gpu=2")), 2)

    def test_multi_slot_meter_respects_capacity(self):
        state = self.frontier_state(".meters: [gpu*2]", ".meters: [gpu]")
        self.assertEqual(len(self.batch(state, "--sem-capacity", "gpu=2")), 1)


class Mutation(Harness):
    def test_add_edge_rewrites_only_the_blocked_by_line(self):
        state = plan_state()
        before = state["issues"][f"{HOME}#2"]["body"]
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--add-edge", f"{ECHO}#6->{HOME}#2")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        after = self.current()["issues"][f"{HOME}#2"]["body"]
        self.assertEqual(after, before.replace(f".blocked_by: [{HOME}#1]", f".blocked_by: [{HOME}#1, {ECHO}#6]"))
        self.assertEqual(r["mutation"]["parent"], f"{ECHO}#6")

    def test_edge_into_another_repository_uses_relative_form_there(self):
        state = plan_state()
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--add-edge", f"{ECHO}#5->{ECHO}#6")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn(f".blocked_by: [{ECHO}#5]", self.current()["issues"][f"{ECHO}#6"]["body"])

    def test_cycle_restores_the_original_body(self):
        state = plan_state()
        before = state["issues"][f"{ECHO}#5"]["body"]
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--add-edge", f"{HOME}#2->{ECHO}#5")
        r = self.out(p)
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(r["mutation"]["rolled_back"])
        self.assertEqual(self.current()["issues"][f"{ECHO}#5"]["body"], before)

    def test_remove_edge(self):
        p = self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9", "--remove-edge", f"{HOME}#1->{HOME}#2")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn(".blocked_by: []", self.current()["issues"][f"{HOME}#2"]["body"])

    def test_owner_is_required_for_another_repository(self):
        p = self.run_dag(plan_state(), "--from-github", "--add-edge", "echo#5->#2")
        self.assertEqual(p.returncode, 1)
        self.assertIn("Invalid edge syntax", p.stdout)

    def test_edit_refuses_a_child_without_frontmatter(self):
        p = self.run_dag(plan_state(), "--from-github", "--add-edge", f"{HOME}#1->{BUNNY}#110")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(self.current()["issues"][f"{BUNNY}#110"]["body"], "Plain body.")


class Mirror(Harness):
    def test_relationship_drift_is_reported(self):
        state = plan_state()
        state["blocked_by"] = {f"{HOME}#2": [f"{HOME}#1"], f"{HOME}#1": [f"{BUNNY}#110"]}
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--compare-relationships"))
        d = r["relationship_drift"]
        self.assertIn(f"{ECHO}#5 -> {HOME}#1", d["only_in_frontmatter"])
        self.assertIn(f"{BUNNY}#110 -> {HOME}#1", d["only_in_github"])
        self.assertNotIn(f"{HOME}#1 -> {HOME}#2", d["only_in_frontmatter"])

    def test_roadmap_renders(self):
        p = self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9", "--emit-roadmap")
        self.assertEqual(p.returncode, 0, p.stdout[-600:])
        self.assertIn(f"{ECHO}#6", p.stdout)


class Trust(Harness):
    """docs/threat-model.md controls C1-C5 and C18."""

    def untrusted_ids(self, r):
        return [u["id"] for u in r["source"]["untrusted_issues"]]

    def test_untrusted_seed_is_listed_and_never_a_node(self):
        state = plan_state()
        state["issues"][f"{HOME}#77"] = issue(177, "Free money", fm(f"{HOME}#77"), author=STRANGER, association="NONE")
        p = self.run_dag(state, "--from-github")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertNotIn(f"{HOME}#77", self.ids(r))
        self.assertNotIn(f"{HOME}#77", [b["id"] for b in r["conflict_free_frontier_batch"]])
        entry = next(u for u in r["source"]["untrusted_issues"] if u["id"] == f"{HOME}#77")
        self.assertEqual(entry["author"], STRANGER)
        self.assertNotIn("title", entry)

    def test_untrusted_editor_makes_a_trusted_issue_an_opaque_blocker(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", STRANGER]
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{HOME}#1", self.untrusted_ids(r))
        node = self.node(r, f"{HOME}#1")
        self.assertTrue(node["opaque"] and node["untrusted"])
        self.assertEqual(node["title"], "(untrusted issue)")
        self.assertEqual(self.node(r, f"{HOME}#2")["open_parents"], [f"{HOME}#1"])
        self.assertNotIn(f"{HOME}#1", [b["id"] for b in r["conflict_free_frontier_batch"]])

    def test_allowlisted_login_is_trusted(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", STRANGER]
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--trust", STRANGER))
        self.assertEqual(self.untrusted_ids(r), [])
        self.assertFalse(self.node(r, f"{HOME}#1")["opaque"])

    def test_collaborator_check_trusts_an_editor(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", "carol"]
        state["collaborators"] = {HOME: ["carol"]}
        self.assertEqual(self.untrusted_ids(self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))), [])

    def test_collaborator_check_that_cannot_run_is_untrusted(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", "carol"]
        state["collaborators_forbidden"] = True
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
        self.assertTrue(any("collaborator check failed" in why for u in r["source"]["untrusted_issues"] for why in u["reasons"]))

    def test_codeowners_allowlists_per_repository(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", "carol"]
        state["codeowners"] = {HOME: {".github/CODEOWNERS": "# owners\n* @carol @flyingrobots/core\ndocs/ docs@example.com\n"}}
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--trust-codeowners"))
        self.assertEqual(self.untrusted_ids(r), [])
        self.assertEqual(r["source"]["trust"]["codeowners"][HOME], ["carol"])
        self.assertEqual(r["source"]["trust"]["codeowners_teams_not_expanded"], {HOME: ["flyingrobots/core"]})

    def test_association_only_counts_inside_the_scope(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=["mallory/trap#1"])
        state["issues"]["mallory/trap#1"] = issue(31337, "Trap", fm("mallory/trap#1"), author=STRANGER, association="OWNER")
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        r = self.out(p)
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(any("outside the trusted repositories" in v for v in r["frontmatter"]["violations"][f"{HOME}#1"]))
        self.assertNotIn(["api", "repos/mallory/trap/issues/1"], self.calls())

    def test_trust_owner_widens_the_scope(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=["partner/lib#1"])
        state["issues"]["partner/lib#1"] = issue(4242, "Partner lib", fm("partner/lib#1"), author="pat", association="OWNER")
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--trust-owner", "partner")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertIn("partner/lib#1", self.ids(r))

    def test_root_outside_the_scope_is_refused(self):
        p = self.run_dag(plan_state(), "--from-github", "--root", "mallory/trap#1")
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertNotIn(["api", "repos/mallory/trap/issues/1"], self.calls())

    def test_untrusted_descendants_do_not_inflate_ranking(self):
        base = self.out(self.run_dag(plan_state(), "--from-github"))
        state = plan_state()
        for n in range(50, 60):
            state["issues"][f"{HOME}#{n}"] = issue(1000 + n, "Fake dependent", fm(f"{HOME}#{n}", blocked_by=[f"{HOME}#2"]), author=STRANGER, association="NONE")
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(self.node(r, f"{HOME}#2")["priority_score"], self.node(base, f"{HOME}#2")["priority_score"])

    def test_fork_pr_does_not_mark_a_task_in_flight(self):
        state = plan_state()
        state["prs"] = [{"number": 7, "isDraft": True, "url": "u", "author": {"login": STRANGER}, "isCrossRepository": True, "closingIssuesReferences": [closing(2)]}]
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(self.node(r, f"{HOME}#2")["status"], "open")
        self.assertEqual(self.node(r, f"{HOME}#2")["linked_open_prs"], [])
        self.assertEqual(r["source"]["untrusted_linked_prs"][0]["closes"], [f"{HOME}#2"])

    def test_same_repository_pr_by_a_trusted_author_marks_in_flight(self):
        state = plan_state()
        state["prs"] = [{"number": 8, "isDraft": False, "url": "u", "author": {"login": "owner"}, "isCrossRepository": False, "closingIssuesReferences": [closing(2)]}]
        state["collaborators"] = {HOME: ["owner"]}
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(self.node(r, f"{HOME}#2")["status"], "in-progress")
        self.assertEqual(r["source"]["untrusted_linked_prs"], [])

    def test_pr_without_trust_fields_is_untrusted(self):
        state = plan_state()
        state["prs"] = [{"number": 9, "isDraft": False, "url": "u", "closingIssuesReferences": [closing(2)]}]
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(self.node(r, f"{HOME}#2")["status"], "open")
        self.assertEqual(len(r["source"]["untrusted_linked_prs"]), 1)

    def test_add_edge_refuses_an_untrusted_child_without_writing(self):
        state = plan_state()
        state["issues"][f"{HOME}#2"].update(author=STRANGER, association="NONE")
        before = state["issues"][f"{HOME}#2"]["body"]
        p = self.run_dag(state, "--from-github", "--add-edge", f"{ECHO}#6->{HOME}#2")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(self.current()["issues"][f"{HOME}#2"]["body"], before)
        self.assertFalse(any("PATCH" in c for c in self.calls()))

    def test_add_edge_refuses_a_parent_outside_the_scope(self):
        p = self.run_dag(plan_state(), "--from-github", "--add-edge", f"mallory/trap#1->{HOME}#2")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertFalse(any("PATCH" in c for c in self.calls()))

    def test_trust_lookup_failure_fails_closed(self):
        state = plan_state()
        state["fail_graphql"] = True
        p = self.run_dag(state, "--from-github")
        self.assertEqual(p.returncode, 2, p.stdout)

    def test_edit_history_is_paginated(self):
        state = plan_state()
        state["edits_page_size"] = 2
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", "owner", "owner", STRANGER]
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{HOME}#1", self.untrusted_ids(r))

    def test_untrusted_titles_never_render(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", STRANGER]
        state["issues"][f"{HOME}#1"]["title"] = "<img src=x onerror=alert(1)> PWNED"
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--emit-roadmap")
        self.assertEqual(p.returncode, 0, p.stdout[-400:])
        self.assertNotIn("PWNED", p.stdout)

    def test_rendered_cells_escape_html(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["title"] = "Home <one>"
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--emit-roadmap")
        self.assertIn("Home &lt;one&gt;", p.stdout)
        self.assertNotIn("Home <one>", p.stdout)

    def test_trust_flags_require_from_github(self):
        p = self.run_dag(plan_state(), "--trust", STRANGER)
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
