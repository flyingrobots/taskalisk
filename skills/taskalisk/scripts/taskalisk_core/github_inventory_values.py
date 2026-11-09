"""Validate CLI issue-inventory fields before summarizing them."""

from __future__ import annotations

from typing import TypedDict, cast

from .github_json import object_fields


class InventoryIssue(TypedDict):
    """The checked public summary of an issue returned by the CLI inventory."""

    number: int
    title: str
    milestone: str | None
    labels: list[str]
    url: str


def _fields(value: object, location: str) -> dict[str, object]:
    """Require an object without replacing falsey malformed values."""
    fields = object_fields(value)
    if fields is None:
        message = f"{location} must be an object"
        raise ValueError(message)
    return fields


def _text(value: object, location: str) -> str:
    """Preserve text, including empty display values, without coercion."""
    if not isinstance(value, str):
        message = f"{location} must be text"
        raise TypeError(message)
    return value


def _labels(value: object) -> list[str]:
    """Require every label's name before returning the complete ordered list."""
    if not isinstance(value, list):
        message = "labels must be an array"
        raise TypeError(message)
    # The runtime check establishes only the container; members remain objects.
    labels = cast("list[object]", value)
    return [_text(_fields(label, "label").get("name"), "label name") for label in labels]


def _milestone(fields: dict[str, object]) -> str | None:
    """Require explicit null or an object with a textual milestone title."""
    if "milestone" not in fields:
        message = "inventory issue has no milestone field"
        raise ValueError(message)
    value = fields["milestone"]
    if value is None:
        return None
    return _text(_fields(value, "milestone").get("title"), "milestone title")


def parse_inventory_issue(value: object) -> InventoryIssue:
    """Admit consumed fields without coercion or partial label results."""
    fields = _fields(value, "inventory issue")
    number = fields.get("number")
    if type(number) is not int or number <= 0:
        message = "issue number must be a positive integer"
        raise ValueError(message)
    return {
        "number": number,
        "title": _text(fields.get("title"), "title"),
        "milestone": _milestone(fields),
        "labels": _labels(fields.get("labels")),
        "url": _text(fields.get("url"), "url"),
    }
