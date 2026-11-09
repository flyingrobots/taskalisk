"""Describe edge-edit bookkeeping without claiming remote atomicity."""

from __future__ import annotations

from typing import Literal, TypedDict

from .issue_refs import IssueRef


class EdgeUndo(TypedDict):
    """The checked child and original body retained by the existing rollback path."""

    child: IssueRef
    old_body: str
    changed: bool


class _MutationFields(TypedDict):
    """Required public mutation metadata after the existing edit path returns."""

    type: Literal["add_blocked_by", "remove_blocked_by"]
    parent: str
    child: str
    changed: bool
    reason: str
    recorded_in: str


class EdgeMutation(_MutationFields, total=False):
    """Optional rollback evidence; issue #1 owns the replacement write contract."""

    rolled_back: bool
    rollback_errors: list[dict[str, str]]
