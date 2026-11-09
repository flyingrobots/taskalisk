"""Check Mutation behavior through the public CLI."""

from cli_fixture import BUNNY, ECHO, HOME, Harness, plan_state
from fake_values import field


class Mutation(Harness):
    """Verify edge edits and recovery against persisted issue bodies."""

    def test_add_edge_rewrites_only_the_blocked_by_line(self) -> None:
        """Adding a dependency changes only the stored .blocked_by line."""
        state = plan_state()
        before = state["issues"][f"{HOME}#2"]["body"]
        p = self.run_dag(
            state, "--from-github", "--root", f"{HOME}#9", "--add-edge", f"{ECHO}#6->{HOME}#2"
        )
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        after = self.current_body(f"{HOME}#2")
        self.assertEqual(
            after, before.replace(f".blocked_by: [{HOME}#1]", f".blocked_by: [{HOME}#1, {ECHO}#6]")
        )
        self.assertEqual(field(r, "mutation", "parent"), f"{ECHO}#6")

    def test_edge_into_another_repository_uses_relative_form_there(self) -> None:
        """An edge within another repository retains its fully qualified parent reference."""
        state = plan_state()
        p = self.run_dag(
            state, "--from-github", "--root", f"{HOME}#9", "--add-edge", f"{ECHO}#5->{ECHO}#6"
        )
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn(f".blocked_by: [{ECHO}#5]", self.current_body(f"{ECHO}#6"))

    def test_cycle_restores_the_original_body(self) -> None:
        """Cycle restores the original body."""
        state = plan_state()
        before = state["issues"][f"{ECHO}#5"]["body"]
        p = self.run_dag(
            state, "--from-github", "--root", f"{HOME}#9", "--add-edge", f"{HOME}#2->{ECHO}#5"
        )
        r = self.out(p)
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(field(r, "mutation", "rolled_back"))
        self.assertEqual(self.current_body(f"{ECHO}#5"), before)

    def test_remove_edge(self) -> None:
        """Removing the sole parent leaves an empty blocked_by list in the stored body."""
        p = self.run_dag(
            plan_state(),
            "--from-github",
            "--root",
            f"{HOME}#9",
            "--remove-edge",
            f"{HOME}#1->{HOME}#2",
        )
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn(".blocked_by: []", self.current_body(f"{HOME}#2"))

    def test_owner_is_required_for_another_repository(self) -> None:
        """An edge argument must include qualified repository identities."""
        p = self.run_dag(plan_state(), "--from-github", "--add-edge", "echo#5->#2")
        self.assertEqual(p.returncode, 1)
        self.assertIn("Invalid edge syntax", p.stdout)

    def test_edit_refuses_a_child_without_frontmatter(self) -> None:
        """Edit refuses a child without frontmatter."""
        p = self.run_dag(plan_state(), "--from-github", "--add-edge", f"{HOME}#1->{BUNNY}#110")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(self.current_body(f"{BUNNY}#110"), "Plain body.")
