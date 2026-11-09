"""Admit PR fields before linking tasks or returning provider inventory."""

from __future__ import annotations

from typing import Literal, TypedDict, cast

from .github_json import object_fields
from .identities import OWNER_RE
from .issue_refs import IssueRef


class PrAuthor(TypedDict):
    """A checked CLI author identity with an explicit actor type."""

    login: str
    type: Literal["User", "Bot"]


class PullRequest(TypedDict):
    """Checked linking fields alongside opaque inventory-only wire values."""

    number: int
    isDraft: bool
    url: str
    closes: list[IssueRef]
    author: PrAuthor | None
    cross_repository: bool | None
    wire: dict[str, object]


def _fields(value: object, location: str) -> dict[str, object]:
    """Require an object without replacing falsey values with empty objects."""
    fields = object_fields(value)
    if fields is None:
        message = f"{location} must be an object"
        raise ValueError(message)
    return fields


def _text(value: object, location: str) -> str:
    """Require actual text, including empty display text."""
    if not isinstance(value, str):
        message = f"{location} must be text"
        raise TypeError(message)
    return value


def _boolean(value: object, location: str) -> bool:
    """Require Boolean evidence without using truthiness or integer coercion."""
    if not isinstance(value, bool):
        message = f"{location} must be a Boolean"
        raise TypeError(message)
    return value


def _number(value: object, location: str) -> int:
    """Require a positive integer, excluding bool despite its int inheritance."""
    if type(value) is not int or value <= 0:
        message = f"{location} must be a positive integer"
        raise ValueError(message)
    return value


def _author(value: object) -> PrAuthor | None:
    """Preserve missing authors; classify present identities only from typed evidence."""
    if value is None:
        return None
    fields = _fields(value, "author")
    login = _text(fields.get("login"), "author login")
    if not login:
        message = "author login must be nonempty text"
        raise ValueError(message)
    is_bot = _boolean(fields.get("is_bot"), "author is_bot")
    return {"login": login, "type": "Bot" if is_bot else "User"}


def _closing_reference(value: object) -> IssueRef:
    """Require the explicit repository identity; never default to the home repository."""
    fields = _fields(value, "closing issue")
    number = _number(fields.get("number"), "closing issue number")
    repo = _fields(fields.get("repository"), "closing repository")
    owner = _fields(repo.get("owner"), "closing repository owner")
    login = _text(owner.get("login"), "closing repository owner login")
    name = _text(repo.get("name"), "closing repository name")
    if not OWNER_RE.fullmatch(login) or not OWNER_RE.fullmatch(name):
        message = "closing repository identity must contain an owner and repository name"
        raise ValueError(message)
    return f"{login}/{name}".lower(), number


def _closes(value: object) -> list[IssueRef]:
    """Admit every closing reference or refuse the complete row."""
    if not isinstance(value, list):
        message = "closingIssuesReferences must be an array"
        raise TypeError(message)
    # The runtime check establishes the container; members remain unadmitted objects.
    values = cast("list[object]", value)
    return [_closing_reference(item) for item in values]


def parse_pull_request(value: object) -> PullRequest:
    """Validate all consumed fields before returning an admitted PR."""
    fields = _fields(value, "PR")
    for key in ("title", "headRefName"):
        _text(fields.get(key), key)
    cross = fields.get("isCrossRepository")
    return {
        "number": _number(fields.get("number"), "PR number"),
        "isDraft": _boolean(fields.get("isDraft"), "isDraft"),
        "url": _text(fields.get("url"), "url"),
        "closes": _closes(fields.get("closingIssuesReferences")),
        "author": _author(fields.get("author")),
        "cross_repository": None if cross is None else _boolean(cross, "isCrossRepository"),
        "wire": fields,
    }
