"""Coordinate dependency resolution, structural analysis, ranking and allocation."""

from __future__ import annotations

from .defaults import DEFAULT_MIN_CONFIDENCE, DENSITY_BAND
from .graph_dependencies import DependencyGraph, collect_dependencies
from .graph_ranking import TaskRanking, rank_tasks
from .graph_resources import allocate_frontier
from .graph_results import GraphMetrics, GraphResult
from .graph_structure import GraphDepths, GraphStructure, analyze_structure, measure_depths
from .graph_values import GraphNode


def _metrics(
    graph: DependencyGraph, structure: GraphStructure, depths: GraphDepths, ranking: TaskRanking
) -> GraphMetrics:
    """Summarize the complete reduced graph without changing its traversal order."""
    count = len(graph["nodes"])
    raw_edges = sum(len(graph["edges"]["children"][node]) for node in graph["nodes"])
    reduced_edges = sum(len(structure["children"][node]) for node in graph["nodes"])
    max_edges = (count * (count - 1)) / 2 if count > 1 else 1
    density = round(reduced_edges / max_edges, 4) if count > 1 else 0.0
    low, high = DENSITY_BAND
    return {
        "merged_count": len(graph["merged"]),
        "open_node_count": count,
        "raw_open_edge_count": raw_edges,
        "reduced_open_edge_count": reduced_edges,
        "transitive_redundant_edges_removed_count": len(structure["redundant"]),
        "edge_density": density,
        "edge_density_band_ok": low <= density <= high if count > 1 else True,
        "max_parallel_width": max((len(wave) for wave in ranking["waves"].values()), default=0),
        "critical_path_length": len(depths["critical_path"]),
        "critical_path": depths["critical_path"],
        "isolated_open_node_count": len(ranking["isolated"]),
        "isolated_open_nodes": ranking["isolated"],
    }


def compile_and_analyze_dag(
    merged: set[str],
    nodes: dict[str, GraphNode],
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    capacities: dict[str, int] | None = None,
) -> GraphResult:
    """Reduce hard dependencies, rank open tasks and allocate a resource-safe batch."""
    graph = collect_dependencies(merged, nodes, min_confidence=min_confidence)
    diagnostics = graph["diagnostics"]
    if diagnostics["unknown"] or diagnostics["stale"]:
        return {
            "ok": False,
            "error": "Unresolved prerequisites: unknown references and/or stale (merged) hints",
            "unknown_dependencies": diagnostics["unknown"],
            "stale_merged_hints": diagnostics["stale"],
            "soft_or_low_confidence_edges": diagnostics["soft"],
        }
    structure = analyze_structure(list(graph["nodes"]), graph["edges"])
    if "error" in structure:
        return structure
    depths = measure_depths(structure)
    ranking = rank_tasks(graph, structure, depths)
    waves = ranking["waves"]
    frontier = waves.get(0, [])
    allocation = allocate_frontier(frontier, capacities)
    return {
        "ok": True,
        "metrics": _metrics(graph, structure, depths, ranking),
        "edges": [
            {
                "from": parent,
                "to": child,
                "evidence": graph["edges"]["evidence"].get((parent, child), ""),
            }
            for parent in graph["nodes"]
            for child in structure["children"][parent]
        ],
        "transitive_redundant_edges_removed": structure["redundant"],
        "soft_or_low_confidence_edges": diagnostics["soft"],
        "unknown_dependencies": [],
        "stale_merged_hints": [],
        "open_frontier_count": len(frontier),
        "open_frontier_ranked": frontier,
        "conflict_free_frontier_batch": allocation["batch"],
        "batch_skipped": allocation["skipped"],
        "semaphores_with_unknown_capacity_treated_as_1": allocation["unknown_capacity"],
        "waves": {f"Wave {level}": waves[level] for level in sorted(waves)},
    }
