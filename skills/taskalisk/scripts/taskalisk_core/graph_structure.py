"""Detect cycles, reduce adjacency and measure prerequisite path depths."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TypedDict

from .graph_dependencies import OpenEdges
from .graph_results import GraphFailure, RedundantEdge


class GraphStructure(TypedDict):
    """Topological order and reachability of an acyclic admitted graph."""

    order: list[str]
    descendants: dict[str, set[str]]
    children: dict[str, list[str]]
    parents: dict[str, list[str]]
    redundant: list[RedundantEdge]


class GraphDepths(TypedDict):
    """Longest incoming/outgoing depths and the deterministically selected path."""

    level: dict[str, int]
    remaining: dict[str, int]
    critical_path: list[str]


def _topological_order(nodes: list[str], edges: OpenEdges) -> tuple[list[str], list[str]]:
    """Return ordered nodes and any nodes left unresolved by a cycle."""
    in_degree = {node: len(edges["parents"][node]) for node in nodes}
    queue = deque(node for node, degree in in_degree.items() if degree == 0)
    order: list[str] = []
    while queue:
        parent = queue.popleft()
        order.append(parent)
        # Dependency resolution admits only open endpoints, so every child has a degree.
        for child in sorted(edges["children"].get(parent, ())):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    return order, [node for node, degree in in_degree.items() if degree > 0]


def _descendants(order: list[str], children: dict[str, set[str]]) -> dict[str, set[str]]:
    """Accumulate reachability after cycle detection on admitted open endpoints."""
    descendants: dict[str, set[str]] = {node: set() for node in order}
    for parent in reversed(order):
        for child in children.get(parent, ()):
            descendants[parent].add(child)
            descendants[parent].update(descendants[child])
    return descendants


def _reduce_edges(
    nodes: list[str], children: dict[str, set[str]], descendants: dict[str, set[str]]
) -> tuple[dict[str, list[str]], dict[str, list[str]], list[RedundantEdge]]:
    """Return reduced children, reduced parents and deterministic shortcut evidence."""
    reduced_children: dict[str, list[str]] = defaultdict(list)
    reduced_parents: dict[str, list[str]] = defaultdict(list)
    redundant: list[RedundantEdge] = []
    open_nodes = set(nodes)
    for parent in nodes:
        siblings = sorted(children.get(parent, set()) & open_nodes)
        for child in siblings:
            via = [other for other in siblings if other != child and child in descendants[other]]
            if via:
                redundant.append({"from": parent, "to": child, "implied_via": via[0]})
            else:
                reduced_children[parent].append(child)
                reduced_parents[child].append(parent)
    return reduced_children, reduced_parents, redundant


def analyze_structure(nodes: list[str], edges: OpenEdges) -> GraphStructure | GraphFailure:
    """Refuse cycles before returning a transitively reduced graph."""
    order, cyclic = _topological_order(nodes, edges)
    if cyclic:
        return {
            "ok": False,
            "error": "Cycle detected in hard structural edges",
            "cyclic_nodes": cyclic,
            "unknown_dependencies": [],
            "stale_merged_hints": [],
        }
    descendants = _descendants(order, edges["children"])
    children, parents, redundant = _reduce_edges(nodes, edges["children"], descendants)
    return {
        "order": order,
        "descendants": descendants,
        "children": children,
        "parents": parents,
        "redundant": redundant,
    }


def measure_depths(structure: GraphStructure) -> GraphDepths:
    """Measure longest paths and preserve lexical tie-breaking between equal paths."""
    levels: dict[str, int] = {}
    predecessors: dict[str, str | None] = {}
    for node in structure["order"]:
        parents = structure["parents"][node]
        if not parents:
            levels[node], predecessors[node] = 0, None
        else:
            best = max(parents, key=lambda parent: (levels[parent], parent))
            levels[node], predecessors[node] = levels[best] + 1, best
    remaining: dict[str, int] = {}
    for node in reversed(structure["order"]):
        children = structure["children"][node]
        remaining[node] = 1 if not children else 1 + max(remaining[child] for child in children)
    critical_path: list[str] = []
    if structure["order"]:
        current: str | None = max(structure["order"], key=lambda node: (levels[node], node))
        while current is not None:
            critical_path.append(current)
            current = predecessors.get(current)
        critical_path.reverse()
    return {"level": levels, "remaining": remaining, "critical_path": critical_path}
