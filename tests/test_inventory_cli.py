"""Verify the public inventory against real Git and the offline GitHub provider."""

from __future__ import annotations

import json

from cli_fixture import ECHO, HOME, Harness, fm, issue
from fake_values import field, records
from fixture_inventory import inventory_issue
from fixture_pr import pull_request

from skills.taskalisk.scripts.taskalisk_core.process import run_cmd_checked


class InventoryCli(Harness):
    """Git baseline failures must not masquerade as issue-inventory refusal."""

    def setUp(self) -> None:
        """Create an owned committed baseline using the bounded real-process adapter."""
        super().setUp()
        commands = [
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "fixture",
            ],
            ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
        ]
        for command in commands:
            ok, _, error = run_cmd_checked(command, cwd=str(self.repo))
            self.assertTrue(ok, f"Cannot prepare isolated Git inventory: {error}")

    def inventory_state(self, rows: list[dict[str, object]]) -> dict[str, object]:
        """Expose exact CLI issue bytes and a complete valid PR record."""
        return {
            "home": HOME,
            "issues": {},
            "blocked_by": {},
            "prs": [pull_request()],
            "issue_inventory_raw": json.dumps(rows),
        }

    def test_malformed_later_issue_refuses_the_complete_inventory(self) -> None:
        """An invalid label container cannot crash or leave the valid earlier issue."""
        bad = inventory_issue()
        bad.update(number=8, labels="enhancement")
        result = self.run_dag(self.inventory_state([inventory_issue(), bad]))
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        with self.subTest(check="diagnostic"):
            self.assertIn("labels must be an array", result.stdout)
        with self.subTest(check="no-partial-inventory"):
            self.assertEqual(field(self.out(result), "github", "open_issues"), [])
        with self.subTest(check="only-issue-error"):
            self.assertEqual(
                [error["source"] for error in records(field(self.out(result), "inventory_errors"))],
                ["gh issue list"],
            )

    def test_issue_number_does_not_alias_a_boolean(self) -> None:
        """A wrong-shaped number cannot be emitted as a valid inventory identifier."""
        bad = inventory_issue()
        bad["number"] = True
        result = self.run_dag(self.inventory_state([bad]))
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        with self.subTest(check="diagnostic"):
            self.assertIn("issue number must be a positive integer", result.stdout)
        with self.subTest(check="no-partial-inventory"):
            self.assertEqual(field(self.out(result), "github", "open_issues"), [])

    def test_inventory_preserves_public_summaries(self) -> None:
        """Valid issue metadata is summarized while PR wire metadata retains its shape."""
        row = inventory_issue()
        row["milestone"] = {"title": "Release", "number": 3}
        result = self.run_dag(self.inventory_state([row]))
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with self.subTest(check="errors"):
            self.assertEqual(self.out(result)["inventory_errors"], [])
        with self.subTest(check="issues"):
            self.assertEqual(
                field(self.out(result), "github", "open_issues"),
                [
                    {
                        "number": 7,
                        "title": "Work",
                        "url": "https://github.com/org/repo/issues/7",
                        "labels": ["enhancement"],
                        "milestone": "Release",
                    }
                ],
            )
        with self.subTest(check="prs"):
            self.assertEqual(field(self.out(result), "github", "open_prs"), [pull_request()])

    def test_transport_failures_are_not_successful_empty_inventories(self) -> None:
        """Both list commands fail with a source-specific error and no admitted rows."""
        for command, field_name in [("pr", "open_prs"), ("issue", "open_issues")]:
            with self.subTest(command=command):
                state = self.inventory_state([inventory_issue()])
                state["fail_command"] = [command, "list"]
                result = self.run_dag(state)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                report = self.out(result)
                self.assertEqual(field(report, "github", field_name), [])
                self.assertEqual(
                    [error["source"] for error in records(report["inventory_errors"])],
                    [f"gh {command} list"],
                )
                self.assertIn("selected command unavailable", result.stdout)

    def test_full_pr_list_refuses_truncation_with_a_one_below_control(self) -> None:
        """The configured 500-row cap is inclusive; a 499-row inventory is retained."""
        for count, expected_exit in [(499, 0), (500, 2)]:
            with self.subTest(count=count):
                state = self.inventory_state([])
                state["prs"] = [
                    dict(pull_request(), number=number) for number in range(1, count + 1)
                ]
                result = self.run_dag(state)
                self.assertEqual(result.returncode, expected_exit, result.stdout + result.stderr)
                report = self.out(result)
                self.assertEqual(
                    len(records(field(report, "github", "open_prs"))), 499 if count == 499 else 0
                )
                self.assertEqual(bool(report["inventory_errors"]), count == 500)

    def test_full_issue_list_refuses_truncation_and_forwards_milestone(self) -> None:
        """The issue cap is inclusive and the operator's milestone reaches the provider."""
        for count, expected_exit in [(999, 0), (1000, 2)]:
            with self.subTest(count=count):
                rows = [dict(inventory_issue(), number=number) for number in range(1, count + 1)]
                result = self.run_dag(self.inventory_state(rows), "--milestone", "Release")
                self.assertEqual(result.returncode, expected_exit, result.stdout + result.stderr)
                report = self.out(result)
                self.assertEqual(
                    len(records(field(report, "github", "open_issues"))), 999 if count == 999 else 0
                )
                self.assertEqual(bool(report["inventory_errors"]), count == 1000)
                self.assertEqual(self.calls()[-1][-2:], ["--milestone", "Release"])

    def test_inventory_projects_only_open_home_issues_without_raw_override(self) -> None:
        """The fake provider's default path preserves labels and filters unrelated rows."""
        state = {
            "home": HOME,
            "blocked_by": {},
            "issues": {
                f"{HOME}#1": issue(101, "Open home", fm(f"{HOME}#1")),
                f"{HOME}#2": issue(
                    102, "Closed home", fm(f"{HOME}#2"), options={"state": "closed"}
                ),
                f"{ECHO}#1": issue(201, "Foreign", fm(f"{ECHO}#1")),
            },
        }
        result = self.run_dag(state)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            field(self.out(result), "github", "open_issues"),
            [
                {
                    "number": 1,
                    "title": "Open home",
                    "url": f"https://github.com/{HOME}/issues/1",
                    "labels": [],
                    "milestone": None,
                }
            ],
        )
