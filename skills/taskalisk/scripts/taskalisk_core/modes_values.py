"""Describe planning configuration and one operator-requested edge edit."""

from __future__ import annotations

from typing import TypedDict

from .authorization import TrustPolicy
from .issue_refs import IssueRef
from .mutation_values import EdgeMutation, EdgeUndo


class PlanOptions(TypedDict):
    """Inputs that control discovery, dependency inclusion and frontier allocation."""

    roots: list[str]
    min_confidence: float
    capacities: dict[str, int]
    compare: bool


class EdgeRequest(TypedDict):
    """An operator's edge expression and the requested edit's public rationale."""

    text: str
    add: bool
    reason: str


class EdgeChange(TypedDict):
    """A parsed dependency edit, before scope and child-body admission."""

    parent: IssueRef
    child: IssueRef
    add: bool


class EditContext(TypedDict):
    """Repository and authorization/error state shared by one edit attempt."""

    repo: str
    home: str
    policy: TrustPolicy
    errors: list[dict[str, str]]


class EditOutcome(TypedDict):
    """Public edit metadata and the original body retained by the existing rollback path."""

    mutation: EdgeMutation
    undo: EdgeUndo
