"""Describe graph inputs admitted by local validation or issue discovery."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict, Union

from .frontmatter_values import FieldValue, Meter

Dependency = TypedDict(
    "Dependency",
    {"from": str, "type": str, "isHard": bool, "confidence": float, "evidence": str},
)
DependencyEntry = Union[str, Dependency]


class NormalizedDependency(Dependency):
    """A dependency with its display hint separated from its reference."""

    merged_hint: bool


class LinkedPr(TypedDict):
    """The checked PR summary displayed alongside a task."""

    number: int
    isDraft: bool
    url: str | None


class GraphNode(TypedDict, total=False):
    """Planning input, retaining invalid frontmatter scalars for diagnostic output."""

    title: str
    url: str | None
    milestone: str | None
    in_filter: bool
    type: FieldValue | None
    workstream: FieldValue | None
    status: FieldValue | None
    size_hours: FieldValue | None
    depends_on: Sequence[DependencyEntry]
    prerequisites: Sequence[DependencyEntry]
    holds: list[str] | None
    resources: list[str] | None
    meters: list[Meter] | None
    linked_open_prs: list[LinkedPr]
    recoverable_branches: list[str]
    opaque: bool
    untrusted: bool


class DagSpec(TypedDict):
    """A complete local spec whose consumed fields have passed admission."""

    merged: set[str]
    nodes: dict[str, GraphNode]
