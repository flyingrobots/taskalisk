"""Describe computed plans, graph failures and later run-level diagnostics."""

from __future__ import annotations

from typing import Literal, TypedDict, Union

from .discovery_values import RelationshipDrift, SourceDetails
from .frontmatter_values import FieldValue, Meter
from .graph_values import LinkedPr
from .mutation_values import EdgeMutation

ReducedEdge = TypedDict("ReducedEdge", {"from": str, "to": str, "evidence": str})
RedundantEdge = TypedDict("RedundantEdge", {"from": str, "to": str, "implied_via": str})
SoftEdge = TypedDict(
    "SoftEdge",
    {"from": str, "to": str, "type": str, "isHard": bool, "confidence": float, "evidence": str},
)


class UnknownDependency(TypedDict):
    """A dependency whose prerequisite has no admitted node or merged hint."""

    node: str
    unknown_prerequisite: str


class StaleHint(TypedDict):
    """A merged hint that contradicts an explicitly open prerequisite."""

    node: str
    prerequisite: str
    prerequisite_status: str


class GraphMetrics(TypedDict):
    """Structural measurements from the complete reduced graph."""

    merged_count: int
    open_node_count: int
    raw_open_edge_count: int
    reduced_open_edge_count: int
    transitive_redundant_edges_removed_count: int
    edge_density: float
    edge_density_band_ok: bool
    max_parallel_width: int
    critical_path_length: int
    critical_path: list[str]
    isolated_open_node_count: int
    isolated_open_nodes: list[str]


class BatchNode(TypedDict):
    """A selected frontier task and the resources reserved for it."""

    id: str
    title: str
    url: str | None
    workstream: FieldValue | None
    priority_score: int
    holds: list[str]
    meters: list[Meter]


class PlannedNode(BatchNode):
    """A ranked node, retaining invalid source metadata for diagnostic JSON."""

    type: FieldValue | None
    milestone: str | None
    in_filter: bool
    status: str
    derived_status: str
    linked_open_prs: list[LinkedPr]
    recoverable_branches: list[str]
    completed_parents: list[str]
    open_parents: list[str]
    directly_unlocks: list[str]
    transitive_unblocks_count: int
    critical_path_remaining_depth: int
    opaque: bool
    untrusted: bool
    size_hours: FieldValue | None


class SkippedNode(TypedDict):
    """A frontier task excluded from this resource allocation."""

    id: str
    reason: str


class FrontmatterReport(TypedDict):
    """Per-issue errors and warnings that remain distinct from graph structure."""

    violating_issues: int
    violations: dict[str, list[str]]
    warnings: dict[str, list[str]]


class ArtifactMeta(TypedDict):
    """The digest of the result before the metadata field is attached."""

    artifact_hash: str


class _ResultDetails(TypedDict, total=False):
    """Evidence attached by command routing after graph analysis."""

    source: SourceDetails
    frontmatter: FrontmatterReport
    relationship_drift: RelationshipDrift
    github_errors: list[dict[str, str]]
    mutation: EdgeMutation
    meta: ArtifactMeta


class _PlanDetails(_ResultDetails, total=False):
    """A computed graph can acquire an error from later admission checks."""

    error: str


class _RunStatus(_PlanDetails):
    """Run validity can become false even after a graph has been computed."""

    ok: bool


class _FailureDetails(_ResultDetails, total=False):
    """Diagnostics specific to the graph condition that stopped analysis."""

    unknown_dependencies: list[UnknownDependency]
    stale_merged_hints: list[StaleHint]
    soft_or_low_confidence_edges: list[SoftEdge]
    cyclic_nodes: list[str]


class GraphFailure(_FailureDetails):
    """A graph refusal always has a false status and an explanatory error."""

    ok: Literal[False]
    error: str


class GraphPlan(_RunStatus):
    """Computed graph data, which later admission checks may still reject."""

    metrics: GraphMetrics
    edges: list[ReducedEdge]
    transitive_redundant_edges_removed: list[RedundantEdge]
    soft_or_low_confidence_edges: list[SoftEdge]
    unknown_dependencies: list[UnknownDependency]
    stale_merged_hints: list[StaleHint]
    open_frontier_count: int
    open_frontier_ranked: list[PlannedNode]
    conflict_free_frontier_batch: list[BatchNode]
    batch_skipped: list[SkippedNode]
    semaphores_with_unknown_capacity_treated_as_1: list[str]
    waves: dict[str, list[PlannedNode]]


GraphResult = Union[GraphPlan, GraphFailure]
