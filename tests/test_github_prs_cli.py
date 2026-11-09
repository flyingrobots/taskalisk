"""Require checked PR fields before linking or returning an inventory."""

from __future__ import annotations

from cli_fixture import HOME, Harness, fm, issue
from fixture_pr import pull_request


def pr_state(prs: list[dict[str, object]]) -> dict[str, object]:
    """Provide one trusted task so a mistaken PR link is observable."""
    return {
        "home": HOME,
        "issues": {f"{HOME}#1": issue(101, "Work", fm(f"{HOME}#1"))},
        "blocked_by": {},
        "collaborators": {HOME: ["owner"]},
        "prs": prs,
    }


class GithubPrsCli(Harness):
    """Malformed PR identity must not promote a task into review."""

    def assert_pr_refusal(self, rows: list[dict[str, object]], diagnostic: str) -> None:
        """Require structured refusal without partial graph or author lookup."""
        result = self.run_dag(pr_state(rows), "--from-github")
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        with self.subTest(check="diagnostic"):
            self.assertIn(diagnostic, result.stdout)
        with self.subTest(check="no-plan"):
            self.assertNotIn("waves", self.out(result))
        with self.subTest(check="no-permission"):
            self.assertFalse(any("collaborators/" in " ".join(call) for call in self.calls()))

    def test_closing_number_cannot_alias_a_different_issue(self) -> None:
        """Boolean and fractional numbers do not coerce into issue 1."""
        for value in (True, 1.5):
            row = pull_request()
            row["closingIssuesReferences"] = [
                {
                    "number": value,
                    "repository": {"name": "geordi", "owner": {"login": "flyingrobots"}},
                }
            ]
            with self.subTest(value=value):
                self.assert_pr_refusal([row], "closing issue number")

    def test_closing_reference_requires_its_repository(self) -> None:
        """A missing repository cannot silently select the home task."""
        row = pull_request()
        row["closingIssuesReferences"] = [{"number": 1}]
        self.assert_pr_refusal([row], "closing repository")

    def test_malformed_bot_discriminator_cannot_become_human(self) -> None:
        """Falsey non-Boolean bot evidence cannot reach collaborator authorization."""
        row = pull_request()
        row["author"] = {"login": "owner", "is_bot": 0}
        self.assert_pr_refusal([row], "is_bot")

    def test_malformed_later_pr_rejects_the_whole_inventory(self) -> None:
        """A valid earlier PR cannot turn a malformed later row into partial success."""
        row = pull_request()
        row.update(number=True)
        self.assert_pr_refusal([pull_request(), row], "PR number")

    def test_malformed_foreign_branch_evidence_is_a_run_error(self) -> None:
        """A present non-Boolean cross-repository value is not an ordinary exclusion."""
        row = pull_request()
        row["isCrossRepository"] = "false"
        self.assert_pr_refusal([row], "isCrossRepository")
