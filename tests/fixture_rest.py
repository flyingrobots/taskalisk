"""Build raw REST issue examples without importing production admission code."""

from __future__ import annotations

from fixture_builders import HOME, fm


def rest_issue() -> dict[str, object]:
    """Supply consumed REST fields independently of the production admission code."""
    return {
        "number": 1,
        "repository_url": f"https://api.github.com/repos/{HOME}",
        "html_url": f"https://github.com/{HOME}/issues/1",
        "title": "Work",
        "state": "open",
        "state_reason": None,
        "body": fm(f"{HOME}#1"),
        "user": {"login": "owner", "type": "User"},
        "author_association": "OWNER",
    }
