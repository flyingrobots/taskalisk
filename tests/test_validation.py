"""Check Validation behavior through the public CLI."""

from cli_fixture import ECHO, HOME, Harness, fm, plan_state
from fake_values import field, fields, items, text


class Validation(Harness):
    """Check frontmatter violations and warnings through the public CLI."""

    def test_list_in_scalar_enum_field_returns_a_structured_violation(self) -> None:
        """Malformed enum values must be refused as data, without a traceback."""
        for key, value in [
            (".dag", "issue-dag/2"),
            (".kind", "task"),
            (".type", "feature"),
            (".status", "active"),
        ]:
            with self.subTest(field=key):
                body = fm(f"{HOME}#1", extra=".status: active")
                body = body.replace(f"{key}: {value}", f"{key}: [{value}]")
                self.assert_violation(body, f"{key} must be")

    def assert_violation(self, body: str, needle: str) -> None:
        """Require exit 1 and the expected violation on the edited issue."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = body
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        r = self.out(p)
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(
            any(
                needle in text(v) for v in items(field(r, "frontmatter", "violations", f"{HOME}#1"))
            ),
            r["frontmatter"],
        )

    def test_unknown_dot_key_fails(self) -> None:
        """An unknown reserved key produces a frontmatter violation."""
        self.assert_violation(
            fm(f"{HOME}#1", extra=f".blockedby: [{HOME}#2]"), "unknown key .blockedby"
        )

    def test_copied_frontmatter_with_wrong_id_fails(self) -> None:
        """Copied frontmatter with wrong ID fails."""
        self.assert_violation(fm(f"{HOME}#2", blocked_by=[f"{ECHO}#5"]), "does not name this issue")

    def test_task_without_blocked_by_fails(self) -> None:
        """A task must explicitly declare its .blocked_by list."""
        self.assert_violation(
            f"```yaml\n.dag: issue-dag/2\n.id: {HOME}#1\n.kind: task\n.type: feature\n```\n",
            "needs .blocked_by",
        )

    def test_container_as_blocker_fails(self) -> None:
        """Container as blocker fails."""
        self.assert_violation(
            fm(f"{HOME}#1", blocked_by=[f"{HOME}#9"]), f"names container {HOME}#9"
        )

    def test_unparseable_line_fails(self) -> None:
        """Unparseable line fails."""
        self.assert_violation(fm(f"{HOME}#1", extra="  nested:\n    - x"), "not 'key: value'")

    def test_large_size_is_a_warning_only(self) -> None:
        """Large size is a warning only."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(
            f"{HOME}#1", blocked_by=[f"{ECHO}#5"], extra=".size_hours: 12"
        )
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn(f"{HOME}#1", fields(field(self.out(p), "frontmatter", "warnings")))
