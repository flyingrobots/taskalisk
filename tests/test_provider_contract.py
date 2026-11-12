"""Keep the offline provider no more capable than the compiler's used protocol."""

import json

from cli_fixture import HOME, Harness, plan_state


class ProviderContract(Harness):
    """Selected failures and unsupported operations must be explicit and non-mutating."""

    def test_selected_command_failure_does_not_hide_an_unrelated_success(self) -> None:
        """The fixture rejects only the chosen prefix and retains the real call log."""
        state: dict[str, object] = dict(plan_state())
        state["fail_command"] = ["pr", "list"]
        result = self.run_provider(state, "pr", "list", "--json", "number")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("selected command unavailable", result.stderr)
        control = self.run_provider(state, "repo", "view")
        self.assertEqual((control.returncode, control.stdout), (0, HOME + "\n"))
        self.assertEqual(self.calls(), [["pr", "list", "--json", "number"], ["repo", "view"]])

    def test_unsupported_issue_and_relationship_writes_leave_fixture_state_intact(self) -> None:
        """The retired native relationship-write paths cannot accidentally accept new calls."""
        cases: list[tuple[str, str, list[str]]] = [
            ("POST", f"repos/{HOME}/issues/2/dependencies/blocked_by", ["-F", "issue_id=101"]),
            ("DELETE", f"repos/{HOME}/issues/2/dependencies/blocked_by/101", []),
            ("PUT", f"repos/{HOME}/issues/2", []),
        ]
        for method, path, flags in cases:
            with self.subTest(method=method):
                state = plan_state()
                result = self.run_provider(state, "api", "-X", method, path, *flags)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIn("unsupported", result.stderr)
                self.assertEqual(json.loads(self.state.read_text()), state)

    def test_unknown_command_path_and_missing_graphql_issue_are_explicit_failures(self) -> None:
        """A fixture routing mistake cannot be mistaken for a successful empty response."""
        cases = [
            (["unknown"], "unsupported command"),
            (["api", "unsupported"], "unsupported path"),
            (
                ["api", "graphql", "-f", "owner=org", "-f", "name=repo", "-F", "number=99"],
                "Could not resolve to an Issue",
            ),
        ]
        for args, diagnostic in cases:
            with self.subTest(args=args):
                result = self.run_provider(plan_state(), *args)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(diagnostic, result.stdout + result.stderr)
