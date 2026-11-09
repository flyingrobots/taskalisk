"""Check PullRequestTrust behavior through the public CLI."""

from cli_fixture import HOME, STRANGER, TrustFixture, closing, fm, issue, plan_state
from fixture_models import FakePullRequest


class PullRequestTrust(TrustFixture):
    def test_pr_inventory_requests_the_trust_fields(self):
        self.run_dag(plan_state(), "--from-github")
        call = next(c for c in self.calls() if c[:2] == ["pr", "list"])
        fields = call[call.index("--json") + 1].split(",")
        self.assertIn("author", fields)
        self.assertIn("isCrossRepository", fields)

    def test_pull_requests_in_the_rest_list_are_not_seeds(self):
        state = plan_state()
        state["issues"][f"{HOME}#300"] = issue(
            300, "A pull request", fm(f"{HOME}#300"), options={"is_pr": True}
        )
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertNotIn(f"{HOME}#300", self.ids(r))

    def test_fork_pr_does_not_mark_a_task_in_flight(self):
        state = plan_state()
        state["prs"] = [
            {
                "number": 7,
                "isDraft": True,
                "url": "u",
                "author": {"login": STRANGER},
                "isCrossRepository": True,
                "closingIssuesReferences": [closing(2)],
            }
        ]
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(self.node(r, f"{HOME}#2")["status"], "open")
        self.assertEqual(self.node(r, f"{HOME}#2")["linked_open_prs"], [])
        self.assertEqual(r["source"]["untrusted_linked_prs"][0]["closes"], [f"{HOME}#2"])

    def test_same_repository_pr_by_a_trusted_author_marks_in_flight(self):
        state = plan_state()
        state["prs"] = [
            {
                "number": 8,
                "isDraft": False,
                "url": "u",
                "author": {"login": "owner"},
                "isCrossRepository": False,
                "closingIssuesReferences": [closing(2)],
            }
        ]
        state["collaborators"] = {HOME: ["owner"]}
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(self.node(r, f"{HOME}#2")["status"], "in-review")
        self.assertEqual(r["source"]["untrusted_linked_prs"], [])

    def test_same_repository_pr_by_an_untrusted_or_missing_author_is_untrusted(self):
        for author in ({"login": STRANGER}, None):
            state = plan_state()
            pr: FakePullRequest = {
                "number": 8,
                "isDraft": False,
                "url": "u",
                "isCrossRepository": False,
                "closingIssuesReferences": [closing(2)],
            }
            if author:
                pr["author"] = author
            state["prs"] = [pr]
            r = self.out(self.run_dag(state, "--from-github"))
            self.assertEqual(self.node(r, f"{HOME}#2")["status"], "open", author)
            self.assertEqual(self.node(r, f"{HOME}#2")["linked_open_prs"], [])
            self.assertEqual(len(r["source"]["untrusted_linked_prs"]), 1)

    def test_pr_without_trust_fields_is_untrusted(self):
        state = plan_state()
        state["prs"] = [
            {"number": 9, "isDraft": False, "url": "u", "closingIssuesReferences": [closing(2)]}
        ]
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(self.node(r, f"{HOME}#2")["status"], "open")
        self.assertEqual(len(r["source"]["untrusted_linked_prs"]), 1)
