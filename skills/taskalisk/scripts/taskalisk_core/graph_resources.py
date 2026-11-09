"""Allocate a ranked frontier under exclusive holds and semaphore capacities."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import TypedDict

from .defaults import BLOCKED_STATUS
from .graph_results import BatchNode, PlannedNode, SkippedNode


class BatchAllocation(TypedDict):
    """Selected tasks, resource refusals and the names using implicit capacity one."""

    batch: list[BatchNode]
    skipped: list[SkippedNode]
    unknown_capacity: list[str]


def lock_keys_conflict(a: str, b: str) -> bool:
    """Detect identical resource keys and ancestor/descendant path overlap."""
    if a == b:
        return True
    a_tree = a if a.endswith("/") else a + "/"
    b_tree = b if b.endswith("/") else b + "/"
    return a_tree.startswith(b_tree) or b_tree.startswith(a_tree)


def any_lock_conflict(required: set[str], held: set[str]) -> bool:
    """Detect whether any requested key overlaps a held resource."""
    return any(lock_keys_conflict(request, existing) for request in required for existing in held)


def allocate_frontier(
    frontier: Sequence[PlannedNode], capacities: Mapping[str, int] | None
) -> BatchAllocation:
    """Select in rank order, excluding blocked/opaque tasks and never exceeding resources."""
    caps = dict(capacities or {})
    unknown_capacity: set[str] = set()
    held: set[str] = set()
    used: dict[str, int] = defaultdict(int)
    batch: list[BatchNode] = []
    skipped: list[SkippedNode] = []
    for candidate in frontier:
        if candidate["status"] == BLOCKED_STATUS or candidate.get("opaque"):
            continue
        required = set(candidate["holds"])
        need: dict[str, int] = defaultdict(int)
        for meter in candidate["meters"]:
            need[meter["name"]] += int(meter["slots"])
        for name in need:
            if name not in caps:
                unknown_capacity.add(name)
        over = [name for name, count in need.items() if used[name] + count > caps.get(name, 1)]
        if any_lock_conflict(required, held) or over:
            skipped.append(
                {
                    "id": candidate["id"],
                    "reason": "holds conflict"
                    if any_lock_conflict(required, held)
                    else f"semaphore full: {', '.join(sorted(over))}",
                }
            )
            continue
        held.update(required)
        for name, count in need.items():
            used[name] += count
        batch.append(
            {
                "id": candidate["id"],
                "title": candidate["title"],
                "url": candidate.get("url"),
                "workstream": candidate["workstream"],
                "priority_score": candidate["priority_score"],
                "holds": sorted(required),
                "meters": candidate["meters"],
            }
        )
    return {"batch": batch, "skipped": skipped, "unknown_capacity": sorted(unknown_capacity)}
