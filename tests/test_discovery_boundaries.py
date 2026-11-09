"""Exercise discovery refusals and status ordering through the real CLI adapter."""

from cli_fixture import HOME, Harness, fm, issue
from fake_values import field, records
from fixture_pr import pull_request
from test_discovery_order import two_seeds


class DiscoveryBoundaries(Harness):
    """A failed prerequisite must not admit later work or fabricate a partial plan."""

    def test_missing_repository_identity_stops_before_inventory(self) -> None:
        """An empty provider identity refuses discovery before any inventory request."""
        state = two_seeds()
        state["home"] = ""
        process = self.run_dag(state, "--from-github")
        result = self.out(process)
        self.assertEqual(process.returncode, 2, result)
        self.assertFalse(result["ok"])
        self.assertNotIn("waves", result)
        self.assertEqual([call[:2] for call in self.calls()], [["repo", "view"]])

    def test_unlinked_pr_needs_no_author_permission_lookup(self) -> None:
        """A PR that links no task contributes nothing and needs no trust lookup."""
        pr = pull_request()
        pr["closingIssuesReferences"] = []
        state = {**two_seeds(), "prs": [pr], "collaborators_forbidden": True}
        process = self.run_dag(state, "--from-github")
        result = self.out(process)
        self.assertEqual(process.returncode, 0, result)
        self.assertEqual(field(result, "source", "untrusted_linked_prs"), [])
        self.assertEqual(self.node(result, f"{HOME}#1")["linked_open_prs"], [])
        self.assertFalse(any("/collaborators/" in " ".join(call) for call in self.calls()))

    def test_pr_permission_failure_stops_before_issue_history(self) -> None:
        """An unavailable PR author check cannot fall through to issue discovery."""
        state = {**two_seeds(), "prs": [pull_request()], "collaborators_forbidden": True}
        process = self.run_dag(state, "--from-github")
        result = self.out(process)
        self.assertEqual(process.returncode, 2, result)
        self.assertFalse(result["ok"])
        self.assertNotIn("waves", result)
        self.assertFalse(any(call[:2] == ["api", "graphql"] for call in self.calls()))

    def test_pr_reference_cannot_become_an_issue_node(self) -> None:
        """A PR used as a task prerequisite is a violation and its body stays unread."""
        state = two_seeds()
        state["issues"][f"{HOME}#2"]["is_pr"] = True
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=[f"{HOME}#2"])
        process = self.run_dag(state, "--from-github", "--root", f"{HOME}#1")
        result = self.out(process)
        self.assertEqual(process.returncode, 1, result)
        self.assertEqual(
            field(result, "frontmatter", "violations", f"{HOME}#2"),
            ["references a pull request, not an issue"],
        )
        self.assertFalse(result["ok"])
        self.assertNotIn("waves", result)
        self.assertFalse(
            any(call[:2] == ["api", "graphql"] and "number=2" in call for call in self.calls())
        )

    def test_status_ranks_active_then_parked_then_open(self) -> None:
        """Resumable parked work ranks below active work and above untouched work."""
        state = two_seeds()
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", extra=".status: parked")
        state["issues"][f"{HOME}#3"] = issue(
            103, "Active", fm(f"{HOME}#3", extra=".status: active")
        )
        process = self.run_dag(state, "--from-github")
        result = self.out(process)
        self.assertEqual(process.returncode, 0, result)
        frontier = records(field(result, "waves", "Wave 0"))
        self.assertEqual(
            [(node["id"], node["status"]) for node in frontier],
            [(f"{HOME}#3", "in-progress"), (f"{HOME}#1", "parked"), (f"{HOME}#2", "open")],
        )
