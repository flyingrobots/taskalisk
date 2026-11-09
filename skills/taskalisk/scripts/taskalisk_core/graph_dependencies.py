"""Resolve declared dependencies into open adjacency and reference diagnostics."""

from __future__ import annotations

from collections import defaultdict
from typing import TypedDict

from .defaults import COMPLETED_STATUSES, MERGED_HINT
from .graph_results import SoftEdge, StaleHint, UnknownDependency
from .graph_values import DependencyEntry, GraphNode, NormalizedDependency


class OpenEdges(TypedDict):
    """Adjacency contains only endpoints present in the admitted open-node map."""

    children: dict[str, set[str]]
    parents: dict[str, set[str]]
    evidence: dict[tuple[str, str], str]


class DependencyDiagnostics(TypedDict):
    """Soft references and unresolved hard references remain separately visible."""

    soft: list[SoftEdge]
    unknown: list[UnknownDependency]
    stale: list[StaleHint]


class DependencyGraph(TypedDict):
    """Owned dependency-resolution state; source node metadata is read only."""

    merged: set[str]
    nodes: dict[str, GraphNode]
    edges: OpenEdges
    completed: dict[str, list[str]]
    diagnostics: DependencyDiagnostics


def strip_merged_hint(ref: str) -> str:
    """Remove the merged display hint and surrounding whitespace."""
    return ref.replace(MERGED_HINT, "").strip()


def normalize_dep_entry(dep: DependencyEntry) -> NormalizedDependency:
    """Separate merged hints from checked dependency fields."""
    if isinstance(dep, str):
        return {
            "from": strip_merged_hint(dep),
            "type": "accepted",
            "isHard": True,
            "confidence": 1.0,
            "evidence": "Declared in DAG specification",
            "merged_hint": MERGED_HINT in dep,
        }
    raw_from = str(dep.get("from", ""))
    return {
        "from": strip_merged_hint(raw_from),
        "type": str(dep.get("type", "accepted")),
        "isHard": bool(dep.get("isHard", True)),
        "confidence": float(dep.get("confidence", 1.0)),
        "evidence": str(dep.get("evidence", "Declared in DAG specification")),
        "merged_hint": MERGED_HINT in raw_from,
    }


def _record_dependency(
    child: str, raw: DependencyEntry, graph: DependencyGraph, min_confidence: float
) -> None:
    """Classify one reference before it can enter the open structural adjacency."""
    edge = normalize_dep_entry(raw)
    parent = edge["from"]
    if not parent:
        return
    diagnostics = graph["diagnostics"]
    if not edge["isHard"] or edge["confidence"] < min_confidence:
        diagnostics["soft"].append(
            {
                "from": parent,
                "to": child,
                "type": edge["type"],
                "isHard": edge["isHard"],
                "confidence": edge["confidence"],
                "evidence": edge["evidence"],
            }
        )
    elif edge["merged_hint"] and parent in graph["nodes"]:
        diagnostics["stale"].append(
            {
                "node": child,
                "prerequisite": parent,
                "prerequisite_status": str(graph["nodes"][parent].get("status", "open")),
            }
        )
    elif parent in graph["merged"] or edge["merged_hint"]:
        graph["merged"].add(parent)
        if parent not in graph["completed"][child]:
            graph["completed"][child].append(parent)
    elif parent in graph["nodes"]:
        graph["edges"]["parents"][child].add(parent)
        graph["edges"]["children"][parent].add(child)
        graph["edges"]["evidence"][(parent, child)] = edge["evidence"]
    else:
        diagnostics["unknown"].append({"node": child, "unknown_prerequisite": parent})


def collect_dependencies(
    merged: set[str], nodes: dict[str, GraphNode], *, min_confidence: float
) -> DependencyGraph:
    """Copy completion state and resolve open nodes in stable identity order."""
    completed = set(merged)
    completed.update(
        node
        for node, meta in nodes.items()
        if str(meta.get("status", "")).strip().lower() in COMPLETED_STATUSES
    )
    graph: DependencyGraph = {
        "merged": completed,
        "nodes": {node: nodes[node] for node in sorted(nodes) if node not in completed},
        "edges": {"children": defaultdict(set), "parents": defaultdict(set), "evidence": {}},
        "completed": defaultdict(list),
        "diagnostics": {"soft": [], "unknown": [], "stale": []},
    }
    for child, meta in graph["nodes"].items():
        for dependency in meta.get("depends_on", meta.get("prerequisites", [])):
            _record_dependency(child, dependency, graph, min_confidence)
    return graph
