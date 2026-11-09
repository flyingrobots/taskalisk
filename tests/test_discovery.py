"""Check Discovery behavior through the public CLI."""

from cli_fixture import BUNNY, ECHO, HOME, Harness, issue, plan_state
from fake_values import field, items, records


class Discovery(Harness):
    def test_cross_repo_closure_from_frontmatter(self):
        p = self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertEqual(
            self.ids(r),
            [f"{BUNNY}#110", f"{ECHO}#5", f"{ECHO}#6", f"{HOME}#1", f"{HOME}#110", f"{HOME}#2"],
        )

    def test_other_repo_card_that_blocks_nothing_at_home_is_found_through_children(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertEqual(self.node(r, f"{ECHO}#6")["open_parents"], [f"{ECHO}#5"])

    def test_relative_refs_resolve_in_the_holding_repository(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{ECHO}#6", items(self.node(r, f"{ECHO}#5")["directly_unlocks"]))

    def test_same_number_in_two_repositories_stays_two_nodes(self):
        ids = self.ids(self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9")))
        self.assertIn(f"{HOME}#110", ids)
        self.assertIn(f"{BUNNY}#110", ids)

    def test_closed_issue_is_a_completed_parent(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertEqual(self.node(r, f"{ECHO}#5")["completed_parents"], [f"{BUNNY}#7"])
        self.assertEqual(
            field(r, "metrics", "critical_path"), [f"{ECHO}#5", f"{HOME}#1", f"{HOME}#2"]
        )

    def test_referenced_issue_without_frontmatter_is_an_opaque_blocker(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertEqual(
            [o["id"] for o in records(field(r, "source", "opaque_nodes"))], [f"{BUNNY}#110"]
        )
        self.assertNotIn(
            f"{BUNNY}#110", [b["id"] for b in records(r["conflict_free_frontier_batch"])]
        )
        self.assertEqual(self.node(r, f"{HOME}#110")["open_parents"], [f"{BUNNY}#110"])

    def test_containers_are_excluded_and_reported(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertNotIn(f"{HOME}#9", self.ids(r))
        self.assertEqual(
            [c["id"] for c in records(field(r, "source", "containers_excluded"))], [f"{HOME}#9"]
        )

    def test_home_issue_without_frontmatter_is_listed_not_a_node(self):
        state = plan_state()
        state["issues"][f"{HOME}#40"] = issue(140, "Legacy", "No frontmatter here.")
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(
            [u["id"] for u in records(field(r, "source", "unmodeled_open_issues"))], [f"{HOME}#40"]
        )
        self.assertNotIn(f"{HOME}#40", self.ids(r))

    def test_labels_are_ignored(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["labels"] = ["type:goalpost", "milestone", "lock:docs/"]
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{HOME}#1", self.ids(r))
        self.assertEqual(self.node(r, f"{HOME}#1")["holds"], [])
