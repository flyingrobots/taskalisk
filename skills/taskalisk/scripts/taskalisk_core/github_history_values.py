"""Validate edit-history response fields before admitting actor identities."""

from __future__ import annotations

from typing import Literal, TypedDict, cast

from .github_json import object_fields


class HistoryEditor(TypedDict):
    """A checked supported actor, or the schema's unknown/deleted identity."""

    login: str | None
    type: Literal["User", "Bot"] | None


class EditHistory(TypedDict):
    """A complete history admitted by the bounded pagination reader."""

    body: str
    editors: list[HistoryEditor]


class HistoryPage(EditHistory):
    """A validated page with explicit termination or a continuation cursor."""

    next_cursor: str | None


def _fields(value: object, location: str) -> dict[str, object]:
    """Require an object without treating a falsey value as an empty object."""
    fields = object_fields(value)
    if fields is None:
        message = f"{location} must be an object"
        raise ValueError(message)
    return fields


def _editor(value: object) -> HistoryEditor:
    """Preserve nullable nodes/editors; reject malformed or unsupported actors."""
    if value is None:
        return {"login": None, "type": None}
    node = _fields(value, "edit node")
    if "editor" not in node:
        message = "edit node has no editor field"
        raise ValueError(message)
    if node["editor"] is None:
        return {"login": None, "type": None}
    actor = _fields(node["editor"], "editor")
    login, kind = actor.get("login"), actor.get("__typename")
    if not isinstance(login, str) or not login:
        message = "editor login must be nonempty text"
        raise ValueError(message)
    if kind == "User":
        return {"login": login, "type": "User"}
    if kind == "Bot":
        return {"login": login, "type": "Bot"}
    message = "editor has an unsupported actor type; expected User or Bot"
    raise ValueError(message)


def _editors(value: object) -> list[HistoryEditor]:
    """Validate every node before admitting any editor from the page."""
    if not isinstance(value, list):
        message = "userContentEdits nodes must be an array"
        raise TypeError(message)
    # The runtime list check establishes only the container, not its members.
    nodes = cast("list[object]", value)
    return [_editor(node) for node in nodes]


def _next_cursor(value: object) -> str | None:
    """Require exact pagination fields and a nonempty cursor when continuation is claimed."""
    page = _fields(value, "pageInfo")
    has_next = page.get("hasNextPage")
    if type(has_next) is not bool:
        message = "pageInfo hasNextPage must be a boolean"
        raise ValueError(message)
    if "endCursor" not in page:
        message = "pageInfo has no endCursor field"
        raise ValueError(message)
    cursor = page["endCursor"]
    if cursor is not None and not isinstance(cursor, str):
        message = "pageInfo endCursor must be text or null"
        raise ValueError(message)
    if has_next and not cursor:
        message = "edit history reports another page but no cursor; refusing a partial editor list"
        raise ValueError(message)
    return cursor if has_next else None


def parse_history_page(value: object) -> HistoryPage:
    """Admit one response; malformed evidence raises TypeError or ValueError."""
    response = _fields(value, "response")
    if "errors" in response:
        message = "response contains GraphQL errors; refusing partial data"
        raise ValueError(message)
    data = _fields(response.get("data"), "data")
    repository = _fields(data.get("repository"), "repository")
    issue = _fields(repository.get("issue"), "issue")
    body = issue.get("body")
    if not isinstance(body, str):
        message = "issue body must be text"
        raise TypeError(message)
    edits = _fields(issue.get("userContentEdits"), "userContentEdits")
    return {
        "body": body,
        "editors": _editors(edits.get("nodes")),
        "next_cursor": _next_cursor(edits.get("pageInfo")),
    }
