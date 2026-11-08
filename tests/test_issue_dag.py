"""Offline tests for issue_dag_snapshot.py. Run: python3 -m unittest discover -s tests"""
import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "issue-dag" / "scripts" / "issue_dag_snapshot.py"
FAKE_GH = pathlib.Path(__file__).resolve().parent / "fake_gh.py"
HOME = "flyingrobots/geordi"
HOUSE_BODY = "# Feature\n\n```text\nDo it.\n```\n\n" + "\n\n".join(f"## {i}. Section" for i in range(1, 10))


def issue(i, title, state="open", labels=(), body=HOUSE_BODY):
    return {"id": i, "title": title, "state": state, "labels": list(labels), "body": body, "state_reason": None}


def single_repo_state():
    return {"home": HOME,
            "issues": {f"{HOME}#1": issue(101, "One"), f"{HOME}#2": issue(102, "Two"), f"{HOME}#3": issue(103, "Three")},
            "blocked_by": {f"{HOME}#2": [f"{HOME}#1"], f"{HOME}#3": [f"{HOME}#2"]}}


def cross_repo_state():
    return {"home": HOME,
            "issues": {
                f"{HOME}#1": issue(101, "Home one"),
                f"{HOME}#2": issue(102, "Home two"),
                f"{HOME}#110": issue(110, "Home 110"),
                f"{HOME}#9": issue(109, "Container", labels=["type:goalpost"]),
                "flyingrobots/echo#5": issue(5005, "Echo five"),
                "flyingrobots/bunny#110": issue(9110, "Bunny 110"),
                "flyingrobots/bunny#7": issue(9007, "Bunny seven, closed", state="closed"),
            },
            "blocked_by": {
                f"{HOME}#1": ["flyingrobots/echo#5"],
                f"{HOME}#2": [f"{HOME}#1"],
                f"{HOME}#110": ["flyingrobots/bunny#110"],
                "flyingrobots/echo#5": ["flyingrobots/bunny#7"],
            }}


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="issue-dag-test-"))
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
        env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                   FAKE_GH_STATE=str(self.state), FAKE_GH_LOG=str(self.log))
        p = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(self.repo), *args],
                           capture_output=True, text=True, env=env)
        return p

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]

    def json_out(self, p):
        try:
            return json.loads(p.stdout)
        except json.JSONDecodeError:
            self.fail(f"not JSON (exit {p.returncode}): {p.stdout[:400]} {p.stderr[:400]}")

    @staticmethod
    def node_ids(result):
        return sorted(n["id"] for items in result["waves"].values() for n in items)


class SingleRepoBehavior(Harness):
    def test_home_ids_stay_bare(self):
        p = self.run_dag(single_repo_state(), "--from-github")
        r = self.json_out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertEqual(self.node_ids(r), ["#1", "#2", "#3"])
        self.assertEqual(r["metrics"]["critical_path"], ["#1", "#2", "#3"])

    def test_verify_dag_spec(self):
        spec = self.tmp / "dag.json"
        spec.write_text(json.dumps({"nodes": {"#1": {"title": "a"}, "#2": {"title": "b", "depends_on": ["#1"]}}}))
        p = subprocess.run([sys.executable, str(SCRIPT), "--verify-dag", str(spec)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.json_out(p)["metrics"]["critical_path"], ["#1", "#2"])


class CrossRepo(Harness):
    def test_blockers_are_queried_in_their_own_repository(self):
        p = self.run_dag(cross_repo_state(), "--from-github")
        r = self.json_out(p)
        self.assertEqual(p.returncode, 0, r)
        paths = [c[-1] if c[0] == "api" and "--paginate" in c else None for c in self.calls()]
        self.assertIn("repos/flyingrobots/echo/issues/5/dependencies/blocked_by", paths)
        self.assertNotIn(f"repos/{HOME}/issues/5/dependencies/blocked_by", paths)
        self.assertIn("flyingrobots/echo#5", self.node_ids(r))

    def test_same_number_in_two_repositories_stays_two_nodes(self):
        r = self.json_out(self.run_dag(cross_repo_state(), "--from-github"))
        ids = self.node_ids(r)
        self.assertIn("#110", ids)
        self.assertIn("flyingrobots/bunny#110", ids)

    def test_closed_cross_repo_blocker_is_a_completed_parent(self):
        r = self.json_out(self.run_dag(cross_repo_state(), "--from-github"))
        echo = next(n for items in r["waves"].values() for n in items if n["id"] == "flyingrobots/echo#5")
        self.assertEqual(echo["completed_parents"], ["flyingrobots/bunny#7"])
        self.assertEqual(r["metrics"]["critical_path"], ["flyingrobots/echo#5", "#1", "#2"])

    def test_containers_stay_excluded(self):
        r = self.json_out(self.run_dag(cross_repo_state(), "--from-github"))
        self.assertNotIn("#9", self.node_ids(r))

    def test_add_edge_from_another_repository(self):
        state = cross_repo_state()
        state["blocked_by"][f"{HOME}#2"] = []
        p = self.run_dag(state, "--from-github", "--add-edge", "flyingrobots/echo#5->#2")
        r = self.json_out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertEqual(r["mutation"]["parent"], "flyingrobots/echo#5")
        self.assertEqual(r["mutation"]["child"], "#2")
        calls = self.calls()
        self.assertIn(["api", "repos/flyingrobots/echo/issues/5", "--jq", ".id"], calls)
        self.assertIn(["api", "-X", "POST", f"repos/{HOME}/issues/2/dependencies/blocked_by", "-F", "issue_id=5005"], calls)

    def test_add_edge_to_another_repository(self):
        state = cross_repo_state()
        p = self.run_dag(state, "--from-github", "--add-edge", "#110->flyingrobots/echo#5")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn(["api", "-X", "POST", "repos/flyingrobots/echo/issues/5/dependencies/blocked_by", "-F", "issue_id=110"], self.calls())

    def test_cross_repo_cycle_is_rolled_back(self):
        p = self.run_dag(cross_repo_state(), "--from-github", "--add-edge", "#1->flyingrobots/echo#5")
        r = self.json_out(p)
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(r["mutation"]["rolled_back"])
        self.assertIn(["api", "-X", "DELETE", "repos/flyingrobots/echo/issues/5/dependencies/blocked_by/101"], self.calls())
        self.assertNotIn(f"{HOME}#1", json.loads(self.state.read_text())["blocked_by"]["flyingrobots/echo#5"])

    def test_owner_is_required_for_another_repository(self):
        p = self.run_dag(cross_repo_state(), "--from-github", "--add-edge", "echo#5->#2")
        self.assertEqual(p.returncode, 1)
        self.assertIn("Invalid edge syntax", p.stdout)

    def test_roadmap_renders_qualified_ids(self):
        p = self.run_dag(cross_repo_state(), "--from-github", "--emit-roadmap")
        self.assertEqual(p.returncode, 0, p.stdout[-600:])
        self.assertIn("flyingrobots/echo#5", p.stdout)

    def test_missing_repository_url_fails_closed(self):
        state = cross_repo_state()
        state["strip_repository_url"] = True
        p = self.run_dag(state, "--from-github")
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertIn("no parseable repository_url", p.stdout)


if __name__ == "__main__":
    unittest.main()
