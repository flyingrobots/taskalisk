"""Check bounded graph semantics independently of the compiler's algorithms."""

from __future__ import annotations

import os
import unittest

from hypothesis import example, given, seed, settings
from hypothesis import strategies as st

from skills.taskalisk.scripts.taskalisk_core.graph import compile_and_analyze_dag
from skills.taskalisk.scripts.taskalisk_core.graph_results import GraphPlan
from skills.taskalisk.scripts.taskalisk_core.graph_values import GraphNode

GRAPH_SEED = int(os.environ.get("TASKALISK_GRAPH_SEED", "20261109"))
NODE_IDS = tuple(str(number) for number in range(8))
POSSIBLE_EDGES = tuple((a, b) for a in NODE_IDS for b in NODE_IDS if a < b)
GRAPHS = st.sets(st.sampled_from(POSSIBLE_EDGES), min_size=1, max_size=28)


def graph_nodes(edges: set[tuple[str, str]]) -> dict[str, GraphNode]:
    """Build eight explicit nodes so isolated work is part of every oracle."""
    return {
        node: {"depends_on": sorted(parent for parent, child in edges if child == node)}
        for node in NODE_IDS
    }


def relation_closure(edges: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Reach a relational fixed point without using topological reduction."""
    reachable = set(edges)
    while True:
        expanded = reachable | {(a, d) for a, b in reachable for c, d in reachable if b == c}
        if expanded == reachable:
            return reachable
        reachable = expanded


def incoming_paths(node: str, edges: set[tuple[str, str]]) -> list[list[str]]:
    """Enumerate all incoming paths in this bounded acyclic fixture universe."""
    parents = [parent for parent, child in edges if child == node]
    if not parents:
        return [[node]]
    return [[*path, node] for parent in parents for path in incoming_paths(parent, edges)]


class GraphProperties(unittest.TestCase):
    """Reduction, layering and path claims must survive generated nonempty DAGs."""

    def setUp(self) -> None:
        """Retain observed input sizes for the external seeded evidence runner."""
        self.generated_edge_counts: list[int] = []

    def plan(self, edges: set[tuple[str, str]]) -> GraphPlan:
        """Require a computed plan for inputs that are acyclic by construction."""
        result = compile_and_analyze_dag(set(), graph_nodes(edges))
        if "metrics" not in result:
            self.fail(f"A generated DAG was refused: {result}")
        self.assertTrue(result["ok"], result)
        return result

    @seed(GRAPH_SEED)
    @settings(max_examples=60, database=None, deadline=500, print_blob=True)
    @given(GRAPHS)
    @example({("0", "1")})
    @example(set(POSSIBLE_EDGES))
    def test_reduction_preserves_reachability_with_no_redundant_edges(
        self, edges: set[tuple[str, str]]
    ) -> None:
        """The reduced relation has the same closure and every retained edge is necessary."""
        self.generated_edge_counts.append(len(edges))
        plan = self.plan(edges)
        reduced = {(edge["from"], edge["to"]) for edge in plan["edges"]}
        expected = relation_closure(edges)
        self.assertEqual(relation_closure(reduced), expected, "reachable task pairs changed")
        self.assertLessEqual(reduced, edges, "reduction invented a dependency")
        for edge in reduced:
            self.assertNotEqual(
                relation_closure(reduced - {edge}),
                expected,
                f"retained redundant edge {edge}; witnessed {len(reduced)} retained edges",
            )

    @seed(GRAPH_SEED)
    @settings(max_examples=60, database=None, deadline=500, print_blob=True)
    @given(GRAPHS)
    @example({("0", "1")})
    @example(set(POSSIBLE_EDGES))
    def test_waves_and_critical_path_match_enumerated_paths(
        self, edges: set[tuple[str, str]]
    ) -> None:
        """Every task survives and its wave equals its longest incomplete prerequisite path."""
        self.generated_edge_counts.append(len(edges))
        plan = self.plan(edges)
        expected = {node: max(map(len, incoming_paths(node, edges))) - 1 for node in NODE_IDS}
        actual = {
            node["id"]: int(wave.removeprefix("Wave "))
            for wave, nodes in plan["waves"].items()
            for node in nodes
        }
        self.assertEqual(actual, expected, "task membership or prerequisite depth changed")
        critical = plan["metrics"]["critical_path"]
        self.assertEqual(len(critical), max(expected.values()) + 1, "critical path is not longest")
        self.assertLessEqual(
            set(zip(critical, critical[1:])), edges, "critical path invented an edge"
        )

    def test_diamond_redundancy_and_path_ties_are_deterministic(self) -> None:
        """An explicit shortcut is accounted for while the longest-path tie stays stable."""
        result = self.plan({("0", "1"), ("0", "2"), ("1", "3"), ("2", "3"), ("0", "3")})
        with self.subTest(check="redundant-evidence"):
            self.assertEqual(
                result["transitive_redundant_edges_removed"],
                [
                    {"from": "0", "to": "3", "implied_via": "1"},
                ],
            )
        with self.subTest(check="path-tie"):
            self.assertEqual(result["metrics"]["critical_path"], ["0", "2", "3"])
