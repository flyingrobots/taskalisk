"""Verify the public inventory against real Git and the offline GitHub provider."""

from __future__ import annotations

import json

from cli_fixture import HOME, Harness
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
