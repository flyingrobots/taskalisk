"""Admit consumed REST issue fields before identity, trust or graph decisions."""

from __future__ import annotations

from typing import Literal, TypedDict

from .github_json import object_fields
from .issue_refs import IssueRef, slug_from_repository_url


class IssueMeta(TypedDict):
    """Checked issue fields used by discovery and author authorization."""

    title: str
    state: Literal["open", "closed"]
    state_reason: str | None
    body: str
    html_url: str
    author: str | None
    author_type: Literal["User", "Bot"] | None
    association: str


class RestIssue(TypedDict):
    """A checked REST identity and metadata, including an explicit PR discriminator."""

    reference: IssueRef
    pull_request: bool
    meta: IssueMeta


def _fields(value: object, location: str) -> dict[str, object]:
    """Require an object without treating a falsey value as an empty object."""
    fields = object_fields(value)
    if fields is None:
        message = f"{location} must be an object"
        raise ValueError(message)
    return fields


def _text(value: object, location: str) -> str:
    """Admit actual text, including empty display text, without coercion."""
    if not isinstance(value, str):
        message = f"{location} must be text"
        raise TypeError(message)
    return value


def _optional_text(value: object, location: str) -> str | None:
    """Preserve the REST schema's nullable text fields."""
    return None if value is None else _text(value, location)


def _reference(fields: dict[str, object]) -> IssueRef:
    """Read the returned identity, preserving transfer targets for caller comparison."""
    number = fields.get("number")
    if type(number) is not int or number <= 0:
        message = "issue number must be a positive integer"
        raise ValueError(message)
    url = _text(fields.get("repository_url"), "repository_url")
    slug = slug_from_repository_url(url)
    if slug is None:
        message = "issue has no parseable repository_url"
        raise ValueError(message)
    return slug, number


def _state(value: object) -> Literal["open", "closed"]:
    """Preserve existing case normalization within the explicit state domain."""
    state = _text(value, "issue state").lower()
    if state == "open":
        return "open"
    if state == "closed":
        return "closed"
    message = "issue state must be open or closed"
    raise ValueError(message)


def _author(fields: dict[str, object]) -> tuple[str | None, Literal["User", "Bot"] | None]:
    """Null users are unknown; a present actor requires a supported typed identity."""
    if "user" not in fields:
        message = "issue has no user field"
        raise ValueError(message)
    if fields["user"] is None:
        return None, None
    user = _fields(fields["user"], "user")
    login = _text(user.get("login"), "author login")
    if not login:
        message = "author login must be nonempty text"
        raise ValueError(message)
    kind = user.get("type")
    if kind == "User":
        return login, "User"
    if kind == "Bot":
        return login, "Bot"
    message = "unsupported author actor type; expected User or Bot"
    raise ValueError(message)


def _is_pull_request(fields: dict[str, object]) -> bool:
    """Identify a PR by the checked discriminator's presence, even for an empty object."""
    if "pull_request" not in fields:
        return False
    _fields(fields["pull_request"], "pull_request")
    return True


def parse_rest_issue(value: object) -> RestIssue:
    """Validate all consumed fields before returning any admitted issue metadata."""
    fields = _fields(value, "issue")
    reference = _reference(fields)
    author, actor_type = _author(fields)
    meta: IssueMeta = {
        "title": _text(fields.get("title"), "title"),
        "state": _state(fields.get("state")),
        "state_reason": _optional_text(fields.get("state_reason"), "state_reason"),
        "body": _optional_text(fields.get("body"), "body") or "",
        "html_url": _text(fields.get("html_url"), "html_url"),
        "author": author,
        "author_type": actor_type,
        "association": _text(fields.get("author_association"), "author_association"),
    }
    return {"reference": reference, "pull_request": _is_pull_request(fields), "meta": meta}
