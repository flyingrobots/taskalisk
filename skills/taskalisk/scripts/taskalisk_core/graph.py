"""Analyze structural dependencies, rank the frontier and allocate resources."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .defaults import (
    BLOCKED_STATUS,
    COMPLETED_STATUSES,
    DEFAULT_MIN_CONFIDENCE,
    DENSITY_BAND,
    FRONTIER_STATUS,
    IN_FLIGHT_STATUSES,
    MERGED_HINT,
    PARKED_STATUS,
    PRIORITY_DEPTH_WEIGHT,
    PRIORITY_DESCENDANTS_WEIGHT,
    PRIORITY_IN_FLIGHT_WEIGHT,
    PRIORITY_PARKED_WEIGHT,
)


def strip_merged_hint(ref: str) -> str:
    return ref.replace(MERGED_HINT, "").strip()


def normalize_dep_entry(dep: str | dict[str, Any]) -> dict[str, Any]:
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


def lock_keys_conflict(a: str, b: str) -> bool:
    if a == b:
        return True
    a_tree = a if a.endswith("/") else a + "/"
    b_tree = b if b.endswith("/") else b + "/"
    return a_tree.startswith(b_tree) or b_tree.startswith(a_tree)


def any_lock_conflict(required: set[str], held: set[str]) -> bool:
    return any(lock_keys_conflict(r, h) for r in required for h in held)


def compile_and_analyze_dag(
    merged: set[str],
    nodes: dict[str, dict[str, Any]],
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    capacities: dict[str, int] | None = None,
) -> dict[str, Any]:
    merged = set(merged)
    for nid, meta in nodes.items():
        if str(meta.get("status", "")).strip().lower() in COMPLETED_STATUSES:
            merged.add(nid)

    open_nodes = sorted(nid for nid in nodes if nid not in merged)
    open_set = set(open_nodes)

    raw_children: dict[str, set[str]] = defaultdict(set)
    raw_parents: dict[str, set[str]] = defaultdict(set)
    completed_parents: dict[str, list[str]] = defaultdict(list)
    edge_evidence: dict[tuple[str, str], str] = {}
    soft_edges: list[dict[str, Any]] = []
    unknown: list[dict[str, str]] = []
    stale_hints: list[dict[str, str]] = []

    for nid in open_nodes:
        for raw_dep in nodes[nid].get("depends_on", nodes[nid].get("prerequisites", [])):
            edge = normalize_dep_entry(raw_dep)
            parent = edge["from"]
            if not parent:
                continue
            if not edge["isHard"] or edge["confidence"] < min_confidence:
                soft_edges.append(
                    {
                        "from": parent,
                        "to": nid,
                        "type": edge["type"],
                        "isHard": edge["isHard"],
                        "confidence": edge["confidence"],
                        "evidence": edge["evidence"],
                    }
                )
                continue
            if edge["merged_hint"] and parent in open_set:
                stale_hints.append(
                    {
                        "node": nid,
                        "prerequisite": parent,
                        "prerequisite_status": str(nodes[parent].get("status", "open")),
                    }
                )
                continue
            if parent in merged or edge["merged_hint"]:
                merged.add(parent)
                if parent not in completed_parents[nid]:
                    completed_parents[nid].append(parent)
            elif parent in open_set:
                raw_parents[nid].add(parent)
                raw_children[parent].add(nid)
                edge_evidence[(parent, nid)] = edge["evidence"]
            else:
                unknown.append({"node": nid, "unknown_prerequisite": parent})

    if unknown or stale_hints:
        return {
            "ok": False,
            "error": "Unresolved prerequisites: unknown references and/or stale (merged) hints",
            "unknown_dependencies": unknown,
            "stale_merged_hints": stale_hints,
            "soft_or_low_confidence_edges": soft_edges,
        }

    in_deg = {nid: len(raw_parents[nid]) for nid in open_nodes}
    queue: deque[str] = deque([nid for nid, d in in_deg.items() if d == 0])
    topo: list[str] = []
    while queue:
        u = queue.popleft()
        topo.append(u)
        for v in sorted(raw_children.get(u, ())):
            if v in in_deg:
                in_deg[v] -= 1
                if in_deg[v] == 0:
                    queue.append(v)
    if len(topo) != len(open_nodes):
        return {
            "ok": False,
            "error": "Cycle detected in hard structural edges",
            "cyclic_nodes": [n for n, d in in_deg.items() if d > 0],
            "unknown_dependencies": [],
            "stale_merged_hints": [],
        }

    descendants: dict[str, set[str]] = {nid: set() for nid in open_nodes}
    for u in reversed(topo):
        for v in raw_children.get(u, ()):
            if v in open_set:
                descendants[u].add(v)
                descendants[u].update(descendants[v])

    reduced_children: dict[str, list[str]] = defaultdict(list)
    reduced_parents: dict[str, list[str]] = defaultdict(list)
    redundant: list[dict[str, str]] = []
    for u in open_nodes:
        children_u = sorted(raw_children.get(u, set()) & open_set)
        for v in children_u:
            via = [w for w in children_u if w != v and v in descendants[w]]
            if via:
                redundant.append({"from": u, "to": v, "implied_via": via[0]})
            else:
                reduced_children[u].append(v)
                reduced_parents[v].append(u)

    level: dict[str, int] = {}
    pred: dict[str, str | None] = {}
    for u in topo:
        if not reduced_parents[u]:
            level[u], pred[u] = 0, None
        else:
            best = max(reduced_parents[u], key=lambda p: (level[p], p))
            level[u], pred[u] = level[best] + 1, best

    remaining: dict[str, int] = {}
    for u in reversed(topo):
        remaining[u] = (
            1 if not reduced_children[u] else 1 + max(remaining[v] for v in reduced_children[u])
        )

    critical_path: list[str] = []
    if open_nodes:
        curr: str | None = max(open_nodes, key=lambda n: (level[n], n))
        while curr is not None:
            critical_path.append(curr)
            curr = pred.get(curr)
        critical_path.reverse()

    n_open = len(open_nodes)
    e_raw = sum(len(raw_children[u] & open_set) for u in open_nodes)
    e_red = sum(len(reduced_children[u]) for u in open_nodes)
    max_edges = (n_open * (n_open - 1)) / 2 if n_open > 1 else 1
    density = round(e_red / max_edges, 4) if n_open > 1 else 0.0

    waves: dict[int, list[dict[str, Any]]] = defaultdict(list)
    isolated: list[str] = []
    for nid in open_nodes:
        meta = nodes[nid]
        if not reduced_parents[nid] and not reduced_children[nid]:
            isolated.append(nid)
        status = str(meta.get("status", "open")).strip().lower()
        in_flight = 1 if status in IN_FLIGHT_STATUSES else 0
        parked = 1 if status == PARKED_STATUS else 0
        score = (
            in_flight * PRIORITY_IN_FLIGHT_WEIGHT
            + parked * PRIORITY_PARKED_WEIGHT
            + len(descendants[nid]) * PRIORITY_DESCENDANTS_WEIGHT
            + remaining[nid] * PRIORITY_DEPTH_WEIGHT
            + len(reduced_children[nid])
        )
        holds = meta.get("holds", meta.get("resources", [])) or []
        meters = meta.get("meters", []) or []
        waves[level[nid]].append(
            {
                "id": nid,
                "title": meta.get("title", ""),
                "url": meta.get("url"),
                "type": meta.get("type", ""),
                "workstream": meta.get("workstream", ""),
                "milestone": meta.get("milestone"),
                "in_filter": meta.get("in_filter", True),
                "status": status,
                "derived_status": FRONTIER_STATUS if level[nid] == 0 else BLOCKED_STATUS,
                "linked_open_prs": meta.get("linked_open_prs", []),
                "recoverable_branches": meta.get("recoverable_branches", []),
                "completed_parents": sorted(completed_parents[nid]),
                "open_parents": sorted(reduced_parents[nid]),
                "directly_unlocks": sorted(reduced_children[nid]),
                "transitive_unblocks_count": len(descendants[nid]),
                "critical_path_remaining_depth": remaining[nid],
                "priority_score": score,
                "holds": sorted(set(holds)),
                "meters": meters,
                "opaque": bool(meta.get("opaque")),
                "untrusted": bool(meta.get("untrusted")),
                "size_hours": meta.get("size_hours"),
            }
        )
    for lvl in waves:
        waves[lvl].sort(key=lambda item: (-item["priority_score"], item["id"]))

    frontier = waves.get(0, [])
    caps = dict(capacities or {})
    unknown_capacity: set[str] = set()
    held: set[str] = set()
    used: dict[str, int] = defaultdict(int)
    batch: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for cand in frontier:
        if cand["status"] == BLOCKED_STATUS or cand.get("opaque"):
            continue  # hand-set block or unmodeled issue: never dispatched
        req = set(cand["holds"])
        need: dict[str, int] = defaultdict(int)
        for meter in cand["meters"]:
            need[meter["name"]] += int(meter["slots"])
        for name in need:
            if name not in caps:
                unknown_capacity.add(name)
        over = [n for n, k in need.items() if used[n] + k > caps.get(n, 1)]
        if any_lock_conflict(req, held) or over:
            skipped.append(
                {
                    "id": cand["id"],
                    "reason": "holds conflict"
                    if any_lock_conflict(req, held)
                    else f"semaphore full: {', '.join(sorted(over))}",
                }
            )
            continue
        held.update(req)
        for n, k in need.items():
            used[n] += k
        batch.append(
            {
                "id": cand["id"],
                "title": cand["title"],
                "url": cand.get("url"),
                "workstream": cand["workstream"],
                "priority_score": cand["priority_score"],
                "holds": sorted(req),
                "meters": cand["meters"],
            }
        )

    lo, hi = DENSITY_BAND
    return {
        "ok": True,
        "metrics": {
            "merged_count": len(merged),
            "open_node_count": n_open,
            "raw_open_edge_count": e_raw,
            "reduced_open_edge_count": e_red,
            "transitive_redundant_edges_removed_count": len(redundant),
            "edge_density": density,
            "edge_density_band_ok": lo <= density <= hi if n_open > 1 else True,
            "max_parallel_width": max((len(w) for w in waves.values()), default=0),
            "critical_path_length": len(critical_path),
            "critical_path": critical_path,
            "isolated_open_node_count": len(isolated),
            "isolated_open_nodes": isolated,
        },
        "edges": [
            {"from": u, "to": v, "evidence": edge_evidence.get((u, v), "")}
            for u in open_nodes
            for v in reduced_children[u]
        ],
        "transitive_redundant_edges_removed": redundant,
        "soft_or_low_confidence_edges": soft_edges,
        "unknown_dependencies": [],
        "stale_merged_hints": [],
        "open_frontier_count": len(frontier),
        "open_frontier_ranked": frontier,
        "conflict_free_frontier_batch": batch,
        "batch_skipped": skipped,
        "semaphores_with_unknown_capacity_treated_as_1": sorted(unknown_capacity),
        "waves": {f"Wave {k}": waves[k] for k in sorted(waves)},
    }
