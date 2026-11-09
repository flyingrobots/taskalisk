"""Check finite history collection and the validated page's actor identities."""

from __future__ import annotations

import unittest

from skills.taskalisk.scripts.taskalisk_core.github_history import HistoryLimits, collect_history
from skills.taskalisk.scripts.taskalisk_core.github_history_values import (
    HistoryPage,
    parse_history_page,
)


def page(cursor: str | None = None) -> HistoryPage:
    """Supply one known-valid page without using the production parser as an oracle."""
    return {"body": "task", "editors": [{"login": "owner", "type": "User"}], "next_cursor": cursor}


class GithubHistory(unittest.TestCase):
    """Only a terminal, bounded, progressing history is returned to authorization."""

    def test_exact_budgets_preserve_history_and_stop_at_terminal_page(self) -> None:
        """The reader neither loses editors nor asks the provider for an extra page."""
        first, last, unused = page("next"), page(), page("unread")
        last["editors"] = [{"login": "app", "type": "Bot"}]
        pages = iter([first, last, unused])
        result = collect_history(pages, HistoryLimits(max_pages=2, max_editors=2))
        with self.subTest(check="values"):
            self.assertEqual(
                result,
                {
                    "body": "task",
                    "editors": [
                        {"login": "owner", "type": "User"},
                        {"login": "app", "type": "Bot"},
                    ],
                },
            )
        with self.subTest(check="no-extra-read"):
            self.assertIs(next(pages, None), unused)

    def test_page_budget_refuses_before_reading_another_page(self) -> None:
        """A nonterminal last allowed page cannot authorize one more provider request."""
        unread = page()
        pages = iter([page("next"), unread])
        with self.subTest(check="refusal"), self.assertRaisesRegex(ValueError, "exceeds 1 pages"):
            collect_history(pages, HistoryLimits(max_pages=1))
        with self.subTest(check="no-extra-read"):
            self.assertIs(next(pages, None), unread)

    def test_editor_budget_counts_the_whole_history(self) -> None:
        """Separately small pages still fail when their aggregate exceeds the cap."""
        with self.assertRaisesRegex(ValueError, "exceeds 1 editors"):
            collect_history([page("next"), page()], HistoryLimits(max_editors=1))

    def test_repeated_cursor_refuses_a_success_shaped_prefix(self) -> None:
        """A repeated cursor is not progress even if a terminal page follows it."""
        with self.assertRaisesRegex(ValueError, "repeated a pagination cursor"):
            collect_history([page("same"), page("same"), page()], HistoryLimits())

    def test_exhaustion_without_a_terminal_page_is_incomplete(self) -> None:
        """Both no pages and a truncated iterator refuse instead of returning a prefix."""
        cases: tuple[list[HistoryPage], ...] = ([], [page("next")])
        for pages in cases:
            with (
                self.subTest(pages=pages),
                self.assertRaisesRegex(ValueError, "without a terminal"),
            ):
                collect_history(pages, HistoryLimits())

    def test_limits_cannot_disable_or_expand_the_ceiling(self) -> None:
        """Policy budgets are bounded positive integers, excluding booleans."""
        for name in ("max_pages", "max_editors"):
            for value in (0, -1, True, 1_000_000):
                with (
                    self.subTest(name=name, value=value),
                    self.assertRaisesRegex(ValueError, "positive integer"),
                ):
                    HistoryLimits(**{name: value})

    def test_page_factory_preserves_typed_actors_and_continuation(self) -> None:
        """User, Bot and schema-null identities remain distinguishable after validation."""
        wire = {
            "data": {
                "repository": {
                    "issue": {
                        "body": "task",
                        "userContentEdits": {
                            "nodes": [
                                {"editor": {"login": "Owner", "__typename": "User"}},
                                {"editor": {"login": "Owner", "__typename": "Bot"}},
                                {"editor": None},
                                None,
                            ],
                            "pageInfo": {"hasNextPage": True, "endCursor": "next"},
                        },
                    }
                }
            }
        }
        self.assertEqual(
            parse_history_page(wire),
            {
                "body": "task",
                "next_cursor": "next",
                "editors": [
                    {"login": "Owner", "type": "User"},
                    {"login": "Owner", "type": "Bot"},
                    {"login": None, "type": None},
                    {"login": None, "type": None},
                ],
            },
        )
