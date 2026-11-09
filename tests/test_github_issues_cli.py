"""Require complete REST issue fields before author trust and graph discovery."""

from __future__ import annotations

import json

from cli_fixture import HOME, Harness, fm, issue, plan_state
from fake_values import field, records
from fixture_rest import rest_issue


class GithubIssuesCli(Harness):
    """Malformed provider fields must not become trusted human-authored tasks."""

    def assert_rest_refusal(self, state: object, diagnostic: str, *args: str) -> None:
        """Require structured refusal, no plan and no edit-history trust work."""
        result = self.run_dag(state, "--from-github", *args)
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        with self.subTest(check="diagnostic"):
            self.assertIn(diagnostic, result.stdout)
        with self.subTest(check="structured"):
            expected_ok = False
            self.assertIs(self.out(result)["ok"], expected_ok)
        with self.subTest(check="no-plan"):
            self.assertNotIn("waves", self.out(result))
        with self.subTest(check="no-history"):
            self.assertFalse(any(call[:2] == ["api", "graphql"] for call in self.calls()))

    def test_unknown_rest_actor_never_inherits_owner_trust(self) -> None:
        """Both seed and referenced issue paths reject an unsupported actor type."""
        state: dict[str, object] = {
            "home": HOME,
            "issues": {
                f"{HOME}#1": issue(
                    101,
                    "Work",
                    fm(f"{HOME}#1"),
                    options={"author_type": "Organization", "association": "OWNER"},
                )
            },
            "blocked_by": {},
        }
        for args in ([], ["--root", f"{HOME}#1"]):
            with self.subTest(args=args):
                self.assert_rest_refusal(state, "unsupported author actor type", *args)

    def test_issue_number_cannot_be_coerced_into_another_issue(self) -> None:
        """True and 1.5 must not alias issue 1 through int conversion."""
        for number in (True, 1.5):
            row = rest_issue()
            row["number"] = number
            state: dict[str, object] = {
                "home": HOME,
                "issues": {},
                "blocked_by": {},
                "issues_list_raw": json.dumps([row]),
            }
            with self.subTest(number=number):
                self.assert_rest_refusal(state, "number must be a positive integer")

    def test_malformed_later_row_refuses_the_complete_inventory(self) -> None:
        """A valid earlier row cannot authorize a partial result or history query."""
        invalid = rest_issue()
        invalid.update(number=2, user=[])
        state: dict[str, object] = {
            "home": HOME,
            "issues": {},
            "blocked_by": {},
            "issues_list_raw": json.dumps([rest_issue()]) + "\n" + json.dumps([invalid]),
        }
        self.assert_rest_refusal(state, "user must be an object")

    def test_listing_cannot_reassign_a_foreign_repository_identity(self) -> None:
        """The home listing must not reinterpret another repository's issue number."""
        row = rest_issue()
        row["repository_url"] = "https://api.github.com/repos/other/repo"
        state: dict[str, object] = {
            "home": HOME,
            "issues": {},
            "blocked_by": {},
            "issues_list_raw": json.dumps([row]),
        }
        self.assert_rest_refusal(state, "listing returned a different repository")

    def test_null_user_stays_untrusted_without_a_history_query(self) -> None:
        """Schema-permitted null identity/body values do not hide an inventory error."""
        row = rest_issue()
        row.update(user=None, body=None)
        state: dict[str, object] = {
            "home": HOME,
            "issues": {},
            "blocked_by": {},
            "issues_list_raw": json.dumps([row]),
        }
        result = self.run_dag(state, "--from-github")
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 0, result.stdout)
        report = self.out(result)
        with self.subTest(check="untrusted"):
            self.assertEqual(
                [
                    (row["id"], row["author"])
                    for row in records(field(report, "source", "untrusted_issues"))
                ],
                [(f"{HOME}#1", None)],
            )
        with self.subTest(check="no-history"):
            self.assertFalse(any(call[:2] == ["api", "graphql"] for call in self.calls()))

    def test_malformed_relationship_row_is_not_silently_dropped(self) -> None:
        """An unreadable mirror identity is a run error, not an empty relationship set."""
        state: dict[str, object] = dict(plan_state())
        state["strip_repository_url"] = True
        state["blocked_by"] = {f"{HOME}#2": [f"{HOME}#1"]}
        result = self.run_dag(state, "--from-github", "--compare-relationships")
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 2, result.stdout)
        with self.subTest(check="diagnostic"):
            self.assertIn("repository_url", result.stdout)
        with self.subTest(check="refusal"):
            expected_ok = False
            self.assertIs(self.out(result)["ok"], expected_ok)

    def test_presence_of_empty_pull_request_object_still_excludes_seed(self) -> None:
        """The REST discriminator is key presence, not truthiness of its value."""
        row = rest_issue()
        row["pull_request"] = {}
        state: dict[str, object] = {
            "home": HOME,
            "issues": {},
            "blocked_by": {},
            "issues_list_raw": json.dumps([row]),
        }
        result = self.run_dag(state, "--from-github")
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 0, result.stdout)
        with self.subTest(check="no-history"):
            self.assertFalse(any(call[:2] == ["api", "graphql"] for call in self.calls()))
        with self.subTest(check="no-nodes"):
            self.assertEqual(self.out(result).get("waves"), {})
