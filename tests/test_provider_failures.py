"""Verify provider failure and seed-limit envelopes through the public compiler."""

import json

from cli_fixture import HOME, Harness, fm, issue
from fake_values import field, records
from fixture_rest import rest_issue


class ProviderFailures(Harness):
    """A transport or complete-list failure never becomes an admitted partial plan."""

    def test_seed_transport_failure_reports_its_source_before_history_queries(self) -> None:
        """A failed seed listing retains its cause and performs no author/editor work."""
        state: dict[str, object] = {
            "home": HOME,
            "blocked_by": {},
            "issues": {},
            "fail_command": ["api", "--paginate", f"repos/{HOME}/issues?state=open&per_page=100"],
        }
        result = self.run_dag(state, "--from-github")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        report = self.out(result)
        self.assertNotIn("waves", report)
        self.assertEqual(
            [error["source"] for error in records(report["github_errors"])],
            [f"gh api repos/{HOME}/issues"],
        )
        self.assertIn("selected command unavailable", result.stdout)
        self.assertFalse(any(call[:2] == ["api", "graphql"] for call in self.calls()))

    def test_seed_limit_is_inclusive_with_an_untrusted_one_below_control(self) -> None:
        """The 999-row control needs no trust queries; the 1000-row listing is refused."""
        for count, expected_exit in [(999, 0), (1000, 2)]:
            with self.subTest(count=count):
                rows = [
                    dict(rest_issue(), number=number, user=None) for number in range(1, count + 1)
                ]
                state: dict[str, object] = {
                    "home": HOME,
                    "blocked_by": {},
                    "issues": {},
                    "issues_list_raw": json.dumps(rows),
                }
                result = self.run_dag(state, "--from-github")
                self.assertEqual(result.returncode, expected_exit, result.stdout + result.stderr)
                report = self.out(result)
                if count == 999:
                    self.assertEqual(report["waves"], {})
                    self.assertEqual(len(records(field(report, "source", "untrusted_issues"))), 999)
                else:
                    self.assertNotIn("waves", report)
                    self.assertIn("refusing a possibly truncated seed set", result.stdout)
                self.assertFalse(any(call[:2] == ["api", "graphql"] for call in self.calls()))

    def test_referenced_issue_bad_json_is_not_a_missing_or_trusted_issue(self) -> None:
        """A malformed single-issue response retains its JSON error before admission."""
        state = {
            "home": HOME,
            "blocked_by": {},
            "issues": {f"{HOME}#1": issue(101, "Work", fm(f"{HOME}#1"))},
            "issue_get_raw": '{"number":1,"number":2}',
        }
        result = self.run_dag(state, "--from-github", "--root", f"{HOME}#1")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        report = self.out(result)
        self.assertNotIn("waves", report)
        self.assertIn("duplicate object key", result.stdout)
        self.assertEqual(
            [error["source"] for error in records(report["github_errors"])],
            [f"gh api repos/{HOME}/issues/1"],
        )
        self.assertFalse(any(call[:2] == ["api", "graphql"] for call in self.calls()))
