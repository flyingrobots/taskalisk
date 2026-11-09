"""Distinguish failed initial publication, failed recovery and unchanged edits."""

from cli_fixture import HOME, Harness, fm
from fake_values import field, fields, records
from test_discovery_order import two_seeds


class MutationFailures(Harness):
    """Observed PATCH failures must not become successful edits or successful rollback."""

    def test_initial_patch_failure_preserves_body_and_is_not_retried(self) -> None:
        """A provider refusal leaves the child unchanged and surfaces a run error."""
        state = two_seeds()
        state["patch_failures"] = [1]
        before = state["issues"][f"{HOME}#2"]["body"]
        process = self.run_dag(state, "--from-github", "--add-edge", f"{HOME}#1->{HOME}#2")
        result = self.out(process)
        self.assertEqual(process.returncode, 2, result)
        self.assertEqual(result["error"], "Frontmatter edit failed")
        self.assertIn("HTTP 500", process.stdout)
        self.assertEqual(self.current_body(f"{HOME}#2"), before)
        self.assertEqual(sum("PATCH" in call for call in self.calls()), 1)

    def test_failed_rollback_reports_the_error_and_keeps_observed_body(self) -> None:
        """A rejected rollback cannot claim restored state or retry the write invisibly."""
        state = two_seeds()
        state["issues"][f"{HOME}#2"]["body"] = fm(f"{HOME}#2", blocked_by=[f"{HOME}#1"])
        state["patch_failures"] = [2]
        process = self.run_dag(state, "--from-github", "--add-edge", f"{HOME}#2->{HOME}#1")
        result = self.out(process)
        self.assertEqual(process.returncode, 1, result)
        mutation = fields(field(result, "mutation"))
        self.assertIs(mutation.get("rolled_back"), expr2=False)
        self.assertIsInstance(mutation.get("rollback_errors"), list)
        errors = records(mutation.get("rollback_errors"))
        self.assertEqual(len(errors), 1)
        self.assertIn("HTTP 500", str(errors[0]["error"]))
        self.assertIn(f".blocked_by: [{HOME}#2]", self.current_body(f"{HOME}#1"))
        self.assertEqual(sum("PATCH" in call for call in self.calls()), 2)

    def test_failed_recompile_does_not_patch_an_unchanged_edit(self) -> None:
        """A no-op add followed by discovery failure needs no compensating write."""
        state = two_seeds()
        before = fm(f"{HOME}#2", blocked_by=[f"{HOME}#1"])
        state["issues"][f"{HOME}#2"]["body"] = before
        state["fail_graphql_for"] = [f"{HOME}#1"]
        process = self.run_dag(state, "--from-github", "--add-edge", f"{HOME}#1->{HOME}#2")
        result = self.out(process)
        self.assertEqual(process.returncode, 2, result)
        mutation = fields(field(result, "mutation"))
        self.assertIs(mutation.get("changed"), expr2=False)
        self.assertNotIn("rolled_back", mutation)
        self.assertEqual(self.current_body(f"{HOME}#2"), before)
        self.assertFalse(any("PATCH" in call for call in self.calls()))
