"""Check MutationTrust behavior through the public CLI."""

from cli_fixture import ECHO, HOME, STRANGER, TrustFixture, fm, issue, plan_state


class MutationTrust(TrustFixture):
    def test_add_edge_rolls_back_when_the_recompile_cannot_run(self):
        state = plan_state()
        state["fail_graphql_for"] = [
            f"{HOME}#1"
        ]  # the child (#2) can be checked; the recompile fails on #1
        before = state["issues"][f"{HOME}#2"]["body"]
        p = self.run_dag(state, "--from-github", "--add-edge", f"{ECHO}#6->{HOME}#2")
        r = self.out(p)
        self.assertEqual(p.returncode, 2, r)
        self.assertTrue(r["mutation"]["rolled_back"])
        self.assertEqual(self.current()["issues"][f"{HOME}#2"]["body"], before)

    def test_add_edge_aborts_when_a_trust_lookup_records_an_error(self):
        state = plan_state()
        state["contents_fail"] = True
        before = state["issues"][f"{HOME}#2"]["body"]
        p = self.run_dag(
            state, "--from-github", "--add-edge", f"{ECHO}#6->{HOME}#2", "--trust-codeowners"
        )
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertEqual(self.current()["issues"][f"{HOME}#2"]["body"], before)
        self.assertFalse(any("PATCH" in c for c in self.calls()))

    def test_add_edge_refuses_a_pull_request_child(self):
        state = plan_state()
        state["issues"][f"{HOME}#300"] = issue(
            300, "A pull request", fm(f"{HOME}#300"), options={"is_pr": True}
        )
        p = self.run_dag(state, "--from-github", "--add-edge", f"{HOME}#1->{HOME}#300")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertFalse(any("PATCH" in c for c in self.calls()))

    def test_add_edge_cycle_rolls_back_even_when_drift_lookup_fails(self):
        state = plan_state()
        state["blocked_by_fail"] = True
        before = state["issues"][f"{ECHO}#5"]["body"]
        p = self.run_dag(
            state,
            "--from-github",
            "--root",
            f"{HOME}#9",
            "--add-edge",
            f"{HOME}#2->{ECHO}#5",
            "--compare-relationships",
        )
        r = self.out(p)
        self.assertEqual(p.returncode, 2, r)
        self.assertTrue(r["mutation"]["rolled_back"])
        self.assertEqual(self.current()["issues"][f"{ECHO}#5"]["body"], before)

    def test_remove_edge_to_an_out_of_scope_parent_is_allowed(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(
            f"{HOME}#1", blocked_by=[f"{ECHO}#5", "mallory/trap#1"]
        )
        p = self.run_dag(
            state,
            "--from-github",
            "--root",
            f"{HOME}#9",
            "--remove-edge",
            f"mallory/trap#1->{HOME}#1",
        )
        self.assertEqual(p.returncode, 0, p.stdout[-500:])
        self.assertIn(f".blocked_by: [{ECHO}#5]", self.current()["issues"][f"{HOME}#1"]["body"])

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
