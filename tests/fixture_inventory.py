"""Build raw issue inventory examples independently of the production parser."""

from __future__ import annotations


def inventory_issue() -> dict[str, object]:
    """Include the fields requested by the CLI inventory, with nullable milestone."""
    return {
        "number": 7,
        "title": "Work",
        "url": "https://github.com/org/repo/issues/7",
        "labels": [{"name": "enhancement", "color": "aabbcc"}],
        "milestone": None,
        "body": "Unused inventory body",
    }
