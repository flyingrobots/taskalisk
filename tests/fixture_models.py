"""Describe owned synthetic GitHub fixtures, including deliberate invalid values."""

from __future__ import annotations

from typing import TypedDict, Union


class FakeEditor(TypedDict, total=False):
    """Synthetic actor fields consumed by the fake provider's edit projection."""

    login: str | None
    type: str


EditorValue = Union[str, None, FakeEditor]


class IssueOptions(TypedDict, total=False):
    """Optional fixture inputs; omission retains the original builder defaults."""

    state: str
    reason: str | None
    author: str | None
    association: str | None
    editors: list[EditorValue] | None
    author_type: str
    is_pr: bool


class _IssueFields(TypedDict):
    """The fields every standard issue fixture supplies."""

    id: int
    title: str
    body: str
    state: str
    state_reason: str | None
    labels: list[str]


class FakeIssue(_IssueFields, total=False):
    """Mutable synthetic metadata, never an admitted production issue."""

    author: str | None
    association: str
    editors: list[EditorValue]
    author_type: str
    is_pr: bool
    graphql_body: str


class FakeRepositoryOwner(TypedDict):
    """A qualified closing reference's owner."""

    login: str


class FakeRepository(TypedDict):
    """A qualified closing reference's repository."""

    name: str
    owner: FakeRepositoryOwner


class FakeClosingReference(TypedDict):
    """A PR's synthetic issue reference."""

    number: int
    repository: FakeRepository


class FakePrAuthor(TypedDict, total=False):
    """Optional author fields exercise the PR adapter's refusal boundary."""

    login: str | None
    is_bot: bool


class FakePullRequest(TypedDict, total=False):
    """PR wire fixtures permit wrong review-state types for negative tests."""

    number: int
    title: str
    headRefName: str
    isDraft: object
    url: str
    author: FakePrAuthor | None
    isCrossRepository: bool | None
    closingIssuesReferences: list[FakeClosingReference]


class _StateFields(TypedDict):
    """Required keys in the reusable multi-repository fixture."""

    home: str
    issues: dict[str, FakeIssue]
    blocked_by: dict[str, list[str]]


class FakePrState(_StateFields):
    """The PR-state fixture always supplies its PR list and collaborator policy."""

    prs: list[FakePullRequest]
    collaborators: dict[str, list[str]]


class FakeState(_StateFields, total=False):
    """Fixture construction contract; raw response overrides remain external bytes."""

    prs: list[FakePullRequest]
    default_author: str
    collaborators: dict[str, list[str] | dict[str, str]]
    codeowners: dict[str, dict[str, str]]
    moved: dict[str, str]
    fail_graphql_for: list[str]
    edits_page_size: int
    graphql_raw: str
    issues_list_raw: str
    blocked_by_fail: bool
    collaborators_forbidden: bool
    patch_failures: list[int]
    patch_count: int
    contents_fail: bool
    graphql_null_edits: bool
    issue_get_returns_list: bool
    issues_list_returns_object: bool
    graphql_no_cursor: bool
    fail_graphql: bool
