"""Rank each open task within its prerequisite wave without allocating resources."""

from __future__ import annotations

from collections import defaultdict
from typing import TypedDict

from .defaults import (
    BLOCKED_STATUS,
    FRONTIER_STATUS,
    IN_FLIGHT_STATUSES,
    PARKED_STATUS,
    PRIORITY_DEPTH_WEIGHT,
    PRIORITY_DESCENDANTS_WEIGHT,
    PRIORITY_IN_FLIGHT_WEIGHT,
    PRIORITY_PARKED_WEIGHT,
)
from .frontmatter_values import Meter
from .graph_dependencies import DependencyGraph
from .graph_results import PlannedNode
from .graph_structure import GraphDepths, GraphStructure


class TaskRanking(TypedDict):
    """Ranked waves and tasks disconnected from all open structural edges."""

    waves: dict[int, list[PlannedNode]]
    isolated: list[str]


def _priority(node: str, status: str, structure: GraphStructure, depths: GraphDepths) -> int:
    """Combine existing status, downstream reach and depth weights."""
    return (
        int(status in IN_FLIGHT_STATUSES) * PRIORITY_IN_FLIGHT_WEIGHT
        + int(status == PARKED_STATUS) * PRIORITY_PARKED_WEIGHT
        + len(structure["descendants"][node]) * PRIORITY_DESCENDANTS_WEIGHT
        + depths["remaining"][node] * PRIORITY_DEPTH_WEIGHT
        + len(structure["children"][node])
    )


def _rank_task(
    node: str, graph: DependencyGraph, structure: GraphStructure, depths: GraphDepths
) -> PlannedNode:
    """Project original metadata and computed relationships into one ranked task."""
    meta = graph["nodes"][node]
    status = str(meta.get("status", "open")).strip().lower()
    holds: list[str] = meta.get("holds", meta.get("resources", [])) or []
    meters: list[Meter] = meta.get("meters", []) or []
    return {
        "id": node,
        "title": meta.get("title", ""),
        "url": meta.get("url"),
        "type": meta.get("type", ""),
        "workstream": meta.get("workstream", ""),
        "milestone": meta.get("milestone"),
        "in_filter": meta.get("in_filter", True),
        "status": status,
        "derived_status": FRONTIER_STATUS if depths["level"][node] == 0 else BLOCKED_STATUS,
        "linked_open_prs": meta.get("linked_open_prs", []),
        "recoverable_branches": meta.get("recoverable_branches", []),
        "completed_parents": sorted(graph["completed"][node]),
        "open_parents": sorted(structure["parents"][node]),
        "directly_unlocks": sorted(structure["children"][node]),
        "transitive_unblocks_count": len(structure["descendants"][node]),
        "critical_path_remaining_depth": depths["remaining"][node],
        "priority_score": _priority(node, status, structure, depths),
        "holds": sorted(set(holds)),
        "meters": meters,
        "opaque": bool(meta.get("opaque")),
        "untrusted": bool(meta.get("untrusted")),
        "size_hours": meta.get("size_hours"),
    }


def rank_tasks(
    graph: DependencyGraph, structure: GraphStructure, depths: GraphDepths
) -> TaskRanking:
    """Keep stable identity ties while ranking tasks within their longest-path wave."""
    waves: dict[int, list[PlannedNode]] = defaultdict(list)
    isolated: list[str] = []
    for node in graph["nodes"]:
        if not structure["parents"][node] and not structure["children"][node]:
            isolated.append(node)
        waves[depths["level"][node]].append(_rank_task(node, graph, structure, depths))
    for wave in waves.values():
        wave.sort(key=lambda item: (-item["priority_score"], item["id"]))
    return {"waves": waves, "isolated": isolated}
