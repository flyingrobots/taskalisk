"""Check Mirror behavior through the public CLI."""

from cli_fixture import BUNNY, ECHO, HOME, Harness, plan_state
from fake_values import fields, items


class Mirror(Harness):
    """Compare relationship mirrors and render the discovered roadmap."""

    def test_relationship_drift_is_reported(self) -> None:
        """Relationship drift is reported."""
        state = plan_state()
        state["blocked_by"] = {f"{HOME}#2": [f"{HOME}#1"], f"{HOME}#1": [f"{BUNNY}#110"]}
        r = self.out(
            self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--compare-relationships")
        )
        d = fields(r["relationship_drift"])
        self.assertIn(f"{ECHO}#5 -> {HOME}#1", items(d["only_in_frontmatter"]))
        self.assertIn(f"{BUNNY}#110 -> {HOME}#1", items(d["only_in_github"]))
        self.assertNotIn(f"{HOME}#1 -> {HOME}#2", items(d["only_in_frontmatter"]))

    def test_roadmap_renders(self) -> None:
        """The generated roadmap includes a discovered task from another repository."""
        p = self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9", "--emit-roadmap")
        self.assertEqual(p.returncode, 0, p.stdout[-600:])
        self.assertIn(f"{ECHO}#6", p.stdout)
