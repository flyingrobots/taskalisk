"""Check RenderingTrust behavior through the public CLI."""

from cli_fixture import BUNNY, ECHO, HOME, STRANGER, TrustFixture, fm, issue, plan_state
from fake_values import field, records


class RenderingTrust(TrustFixture):
    def test_closed_not_planned_untrusted_blocker_leaks_no_title(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(
            f"{HOME}#1", blocked_by=[f"{ECHO}#5", f"{ECHO}#99"]
        )
        state["issues"][f"{ECHO}#99"] = issue(
            5099,
            "SECRET STRANGER TITLE",
            fm(f"{ECHO}#99"),
            options={
                "state": "closed",
                "reason": "not_planned",
                "author": STRANGER,
                "association": "NONE",
            },
        )
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        self.assertEqual(p.returncode, 0, p.stdout[-400:])
        self.assertNotIn("SECRET STRANGER TITLE", p.stdout)
        self.assertEqual(
            records(field(self.out(p), "source", "not_planned_parents"))[0]["title"],
            "(untrusted issue)",
        )

    def test_rendered_cells_escape_links_and_resource_pipes(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["title"] = "[click](https://example.invalid)"
        state["issues"][f"{ECHO}#5"]["body"] = fm(
            f"{ECHO}#5", blocked_by=[f"{BUNNY}#7"], extra=".holds: [a|b]"
        )  # on the frontier, so its Resources cell renders
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--emit-roadmap")
        self.assertNotIn("[click](https://example.invalid)", p.stdout)
        self.assertIn("a\\|b", p.stdout)

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
