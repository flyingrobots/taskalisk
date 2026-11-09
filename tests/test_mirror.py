"""Check Mirror behavior through the public CLI."""

from cli_fixture import BUNNY, ECHO, HOME, Harness, plan_state


class Mirror(Harness):
    def test_relationship_drift_is_reported(self):
        state = plan_state()
        state["blocked_by"] = {f"{HOME}#2": [f"{HOME}#1"], f"{HOME}#1": [f"{BUNNY}#110"]}
        r = self.out(
            self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--compare-relationships")
        )
        d = r["relationship_drift"]
        self.assertIn(f"{ECHO}#5 -> {HOME}#1", d["only_in_frontmatter"])
        self.assertIn(f"{BUNNY}#110 -> {HOME}#1", d["only_in_github"])
        self.assertNotIn(f"{HOME}#1 -> {HOME}#2", d["only_in_frontmatter"])

    def test_roadmap_renders(self):
        p = self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9", "--emit-roadmap")
        self.assertEqual(p.returncode, 0, p.stdout[-600:])
        self.assertIn(f"{ECHO}#6", p.stdout)
