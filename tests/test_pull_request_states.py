"""Check PullRequestStates behavior through the public CLI."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import product

from cli_fixture import HOME, STRANGER, Harness, closing, fm, issue
from fake_values import field, records
from fixture_models import FakePrState


class PullRequestStates(Harness):
    """Derive task status and priority only from admitted PR review states."""

    def state_with_prs(self, drafts: Sequence[object], extra: str = "") -> FakePrState:
        """Supply explicit PR states, including malformed states for refusal tests."""
        return {
            "home": HOME,
            "blocked_by": {},
            "collaborators": {HOME: ["owner"]},
            "issues": {f"{HOME}#1": issue(101, "Work", fm(f"{HOME}#1", extra=extra))},
            "prs": [
                {
                    "number": 10 + i,
                    "title": "Work",
                    "headRefName": "task/work",
                    "isDraft": draft,
                    "url": f"https://github.com/{HOME}/pull/{10 + i}",
                    "author": {"login": "owner", "is_bot": False},
                    "isCrossRepository": False,
                    "closingIssuesReferences": [closing(1)],
                }
                for i, draft in enumerate(drafts)
            ],
        }

    def test_trusted_pr_states_keep_priority_and_render(self) -> None:
        """Trusted PRs retain the expected status, priority and rendered state."""
        for drafts, expected in [
            ([True], "wip"),
            ([False], "in-review"),
            ([True, False], "in-review"),
            ([False, True], "in-review"),
        ]:
            with self.subTest(drafts=drafts):
                state = self.state_with_prs(drafts)
                p = self.run_dag(state, "--from-github")
                self.assertEqual(p.returncode, 0, p.stdout)
                node = self.node(self.out(p), f"{HOME}#1")
                self.assertEqual(node["status"], expected)
                self.assertEqual(node["priority_score"], 1010)
                self.assertEqual([pr["isDraft"] for pr in records(node["linked_open_prs"])], drafts)
                rendered = self.run_dag(state, "--from-github", "--emit-roadmap")
                self.assertEqual(rendered.returncode, 0, rendered.stdout)
                self.assertIn(f"| {expected} |", rendered.stdout)
                self.assertIn(f"({expected})", rendered.stdout)

    def test_untrusted_ready_pr_does_not_promote_a_trusted_draft(self) -> None:
        """Untrusted ready PR does not promote a trusted draft."""
        for foreign, author in [(True, "owner"), (False, STRANGER)]:
            with self.subTest(foreign=foreign, author=author):
                state = self.state_with_prs([True, False])
                state["prs"][1].update(
                    isCrossRepository=foreign, author={"login": author, "is_bot": False}
                )
                p = self.run_dag(state, "--from-github")
                self.assertEqual(p.returncode, 0, p.stdout)
                result = self.out(p)
                node = self.node(result, f"{HOME}#1")
                self.assertEqual(node["status"], "wip")
                self.assertEqual(node["priority_score"], 1010)
                self.assertEqual([pr["number"] for pr in records(node["linked_open_prs"])], [10])
                self.assertEqual(
                    [
                        pr["number"]
                        for pr in records(field(result, "source", "untrusted_linked_prs"))
                    ],
                    [11],
                )

    def test_active_without_a_pr_stays_in_progress(self) -> None:
        """An active task without a linked PR retains its in-progress status."""
        p = self.run_dag(self.state_with_prs([], ".status: active"), "--from-github")
        self.assertEqual(p.returncode, 0, p.stdout)
        node = self.node(self.out(p), f"{HOME}#1")
        self.assertEqual(node["status"], "in-progress")
        self.assertEqual(node["priority_score"], 1010)

    def test_missing_or_invalid_draft_state_fails_closed(self) -> None:
        """Missing or invalid draft state fails closed."""
        for prefix, value in product([[], [True]], [None, "false", 0]):
            with self.subTest(prefix=prefix, value=value):
                state = self.state_with_prs([*prefix, value])
                if value is None:
                    del state["prs"][-1]["isDraft"]
                p = self.run_dag(state, "--from-github")
                self.assertEqual(p.returncode, 2, p.stdout)
                self.assertIn("isDraft", p.stdout)
                self.assertNotIn("waves", self.out(p))
