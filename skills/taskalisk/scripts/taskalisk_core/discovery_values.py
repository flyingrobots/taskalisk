"""Describe discovered issue evidence and its public provenance projection."""

from __future__ import annotations

from typing import TypedDict, Union

from .authorization_values import TrustDescription
from .frontmatter_values import FrontmatterRecord
from .github_issue_values import IssueMeta
from .graph_values import GraphNode
from .issue_refs import IssueRef


class ContainerSummary(TypedDict):
    """A container excluded from executable task nodes."""

    id: str
    number: int
    title: str


class Container(ContainerSummary):
    """A discovered container with its explicitly declared children."""

    children: list[str]


class UnmodeledIssue(TypedDict):
    """A trusted home issue without frontmatter."""

    id: str
    title: str
    url: str


class OpaqueIssue(TypedDict):
    """A referenced trusted issue whose missing model blocks dispatch."""

    id: str
    title: str
    state: str
    referenced_by: list[str]


class UntrustedIssue(TypedDict):
    """Admission evidence that deliberately contains no untrusted title."""

    id: str
    url: str
    state: str
    author: str | None
    reasons: list[str]
    referenced_by: list[str]


class UntrustedPr(TypedDict):
    """An excluded PR and the reason it cannot link a task."""

    number: int
    url: str
    author: str | None
    cross_repository: bool | None
    closes: list[str]
    reason: str


class NotPlannedParent(TypedDict):
    """A closed prerequisite whose closure did not complete its planned work."""

    parent: str
    child: str
    title: str


class DiscoveryFailure(TypedDict):
    """The empty private result returned alongside recorded discovery errors."""

    merged: set[str]
    nodes: dict[str, GraphNode]
    containers: list[Container]
    slug: None


class DiscoveryResult(TypedDict):
    """A complete discovery pass, including violations that prevent dispatch."""

    merged: set[str]
    nodes: dict[str, GraphNode]
    containers: list[Container]
    slug: str
    violations: dict[str, list[str]]
    warnings: dict[str, list[str]]
    unmodeled_open_issues: list[UnmodeledIssue]
    opaque_nodes: list[OpaqueIssue]
    not_planned_parents: list[NotPlannedParent]
    records: dict[IssueRef, FrontmatterRecord]
    fetched: dict[IssueRef, IssueMeta]
    untrusted_issues: list[UntrustedIssue]
    untrusted_linked_prs: list[UntrustedPr]
    trust: TrustDescription


Discovery = Union[DiscoveryResult, DiscoveryFailure]


class SourceDetails(TypedDict, total=False):
    """Provenance fields; standalone local plans may omit this evidence."""

    kind: str
    schema: str
    repository: str
    roots: list[str]
    trust: TrustDescription
    containers_excluded: list[ContainerSummary]
    unmodeled_open_issues: list[UnmodeledIssue]
    untrusted_issues: list[UntrustedIssue]
    untrusted_linked_prs: list[UntrustedPr]
    opaque_nodes: list[OpaqueIssue]
    not_planned_parents: list[NotPlannedParent]


class RelationshipDrift(TypedDict):
    """Differences between authoritative frontmatter and its GitHub mirror."""

    only_in_frontmatter: list[str]
    only_in_github: list[str]
    in_sync: bool
