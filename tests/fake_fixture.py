"""Load owned fixture state and project issue records for the fake provider."""

from __future__ import annotations

import json
import os
import sys
from typing import NoReturn

from fake_values import fields, items


def load() -> dict[str, object]:
    """Read an object boundary; individual wire values remain unvalidated objects."""
    with open(os.environ["FAKE_GH_STATE"], encoding="utf-8") as stream:
        decoded: object = json.load(stream)
    return fields(decoded)


def save(state: dict[str, object]) -> None:
    """Persist the single-process fixture's updated state."""
    with open(os.environ["FAKE_GH_STATE"], "w", encoding="utf-8") as stream:
        json.dump(state, stream)


def fail(message: str) -> NoReturn:
    """Terminate a simulated provider failure with its stderr diagnostic."""
    sys.stderr.write(message + "\n")
    sys.exit(1)


def emit(value: object) -> None:
    """Write one JSON protocol document followed by a newline."""
    sys.stdout.write(json.dumps(value) + "\n")


def issue_table(state: dict[str, object]) -> dict[str, dict[str, object]]:
    """Validate only the containers needed to address synthetic issue records."""
    return {key: fields(value) for key, value in fields(state["issues"]).items()}


def author_of(state: dict[str, object], issue: dict[str, object]) -> object:
    """Preserve explicit null and malformed author values for provider fault tests."""
    return issue.get("author", state.get("default_author", "owner"))


def issue_obj(state: dict[str, object], key: str, record: dict[str, object]) -> dict[str, object]:
    """Project a checked record container without claiming validity of its wire fields."""
    slug, number = key.split("#")
    author = author_of(state, record)
    result: dict[str, object] = {
        "number": int(number),
        "id": record["id"],
        "title": record["title"],
        "state": record["state"],
        "state_reason": record.get("state_reason"),
        "labels": [{"name": label} for label in items(record.get("labels", []))],
        "body": record.get("body", ""),
        "milestone": None,
        "html_url": f"https://github.com/{slug}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{slug}",
        "user": {"login": author, "type": record.get("author_type", "User")} if author else None,
        "author_association": record.get("association", "OWNER"),
    }
    if record.get("is_pr"):
        result["pull_request"] = {"url": f"https://api.github.com/repos/{slug}/pulls/{number}"}
    return result


def strip(state: dict[str, object], obj: dict[str, object]) -> dict[str, object]:
    """Support the existing missing-repository-identity fault fixture."""
    if state.get("strip_repository_url"):
        obj.pop("repository_url", None)
    return obj
