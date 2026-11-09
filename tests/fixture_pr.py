"""Build PR wire examples independently of production admission code."""

from __future__ import annotations

from fixture_builders import HOME, closing


def pull_request() -> dict[str, object]:
    """Supply the fields requested from gh pr list, including typed author evidence."""
    return {
        "number": 10,
        "title": "Implement work",
        "headRefName": "task/1-work",
        "isDraft": False,
        "url": f"https://github.com/{HOME}/pull/10",
        "author": {"login": "owner", "is_bot": False},
        "isCrossRepository": False,
        "closingIssuesReferences": [closing(1)],
    }
