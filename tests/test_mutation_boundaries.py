"""Verify edit refusal and no-op effects through persisted fake-provider state."""

from cli_fixture import HOME, Harness, fm
from fake_values import field
from test_discovery_order import two_seeds


class MutationBoundaries(Harness):
    """Failed prerequisites must stop effects; an unchanged body needs no PATCH."""

    def test_missing_home_identity_stops_an_edit_before_issue_lookup(self) -> None:
        """A failed home lookup cannot select a mutation repository implicitly."""
        state = two_seeds()
        state["home"] = ""
        process = self.run_dag(state, "--from-github", "--add-edge", f"{HOME}#1->{HOME}#2")
        result = self.out(process)
        self.assertEqual(process.returncode, 2, result)
        self.assertEqual(result["error"], "GitHub mutation failed")
        self.assertEqual([call[:2] for call in self.calls()], [["repo", "view"]])

    def test_self_edge_stops_before_child_lookup(self) -> None:
        """A self-edge is a structured input refusal without a child read or write."""
        process = self.run_dag(two_seeds(), "--from-github", "--add-edge", f"{HOME}#1->{HOME}#1")
        result = self.out(process)
        self.assertEqual(process.returncode, 1, result)
        self.assertEqual(result["error"], f"Self-edge rejected: {HOME}#1")
        self.assertEqual([call[:2] for call in self.calls()], [["repo", "view"]])

    def test_missing_child_stops_without_a_write_or_history_lookup(self) -> None:
        """A missing issue is a provider failure, not an empty task to create."""
        process = self.run_dag(two_seeds(), "--from-github", "--add-edge", f"{HOME}#1->{HOME}#99")
        result = self.out(process)
        self.assertEqual(process.returncode, 2, result)
        self.assertEqual(result["error"], "Frontmatter edit failed")
        self.assertFalse(any("PATCH" in call or "graphql" in call for call in self.calls()))

    def test_failed_child_history_preserves_the_original_body(self) -> None:
        """Author admission cannot authorize a write when editor history is unavailable."""
        state = two_seeds()
        state["fail_graphql_for"] = [f"{HOME}#2"]
        before = state["issues"][f"{HOME}#2"]["body"]
        process = self.run_dag(state, "--from-github", "--add-edge", f"{HOME}#1->{HOME}#2")
        self.assertEqual(process.returncode, 2, process.stdout)
        self.assertEqual(self.current_body(f"{HOME}#2"), before)
        self.assertFalse(any("PATCH" in call for call in self.calls()))

    def test_invalid_task_and_container_bodies_are_never_patched(self) -> None:
        """Parsed frontmatter must describe a valid task before its edges can change."""
        bodies = [
            fm(f"{HOME}#2", kind="container", children=[]),
            fm(f"{HOME}#2").replace(".type: feature", ".type: [feature]"),
        ]
        for body in bodies:
            with self.subTest(body=body):
                state = two_seeds()
                state["issues"][f"{HOME}#2"]["body"] = body
                process = self.run_dag(state, "--from-github", "--add-edge", f"{HOME}#1->{HOME}#2")
                self.assertEqual(process.returncode, 1, process.stdout)
                self.assertIn("invalid task frontmatter", process.stdout)
                self.assertEqual(self.current_body(f"{HOME}#2"), body)
                self.assertFalse(any("PATCH" in call for call in self.calls()))

    def test_already_present_add_and_absent_remove_do_not_patch(self) -> None:
        """A successful no-op reports unchanged and does not publish an identical body."""
        for flag, parents in [("--add-edge", [f"{HOME}#1"]), ("--remove-edge", [])]:
            with self.subTest(flag=flag):
                state = two_seeds()
                body = fm(f"{HOME}#2", blocked_by=parents)
                state["issues"][f"{HOME}#2"]["body"] = body
                process = self.run_dag(state, "--from-github", flag, f"{HOME}#1->{HOME}#2")
                result = self.out(process)
                self.assertEqual(process.returncode, 0, result)
                self.assertFalse(field(result, "mutation", "changed"))
                self.assertEqual(self.current_body(f"{HOME}#2"), body)
                self.assertFalse(any("PATCH" in call for call in self.calls()))
