"""Keep graph failures distinct from computed plans rejected by later checks."""

from __future__ import annotations

import json

from cli_fixture import HOME, Harness, fm, issue


class ResultProtocol(Harness):
    """Typed internal results must preserve public diagnostics and selected views."""

    def test_graph_failures_keep_json_diagnostics_when_mermaid_is_requested(self) -> None:
        """Unknown, stale and cyclic prerequisites never become partial diagrams."""
        cases: tuple[tuple[dict[str, object], dict[str, object]], ...] = (
            (
                {"b": {"depends_on": ["missing"]}},
                {
                    "ok": False,
                    "error": "Unresolved prerequisites: unknown references and/or stale (merged) hints",
                    "unknown_dependencies": [{"node": "b", "unknown_prerequisite": "missing"}],
                    "stale_merged_hints": [],
                    "soft_or_low_confidence_edges": [],
                },
            ),
            (
                {"a": {}, "b": {"depends_on": ["a (merged)"]}},
                {
                    "ok": False,
                    "error": "Unresolved prerequisites: unknown references and/or stale (merged) hints",
                    "unknown_dependencies": [],
                    "stale_merged_hints": [
                        {"node": "b", "prerequisite": "a", "prerequisite_status": "open"}
                    ],
                    "soft_or_low_confidence_edges": [],
                },
            ),
            (
                {"a": {"depends_on": ["b"]}, "b": {"depends_on": ["a"]}},
                {
                    "ok": False,
                    "error": "Cycle detected in hard structural edges",
                    "cyclic_nodes": ["a", "b"],
                    "unknown_dependencies": [],
                    "stale_merged_hints": [],
                },
            ),
        )
        path = self.tmp / "spec.json"
        for nodes, expected in cases:
            path.write_text(json.dumps({"nodes": nodes}), encoding="utf-8")
            result = self.run_dag({}, "--verify-dag", str(path), "--emit-mermaid")
            with self.subTest(nodes=nodes, check="exit"):
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            with self.subTest(nodes=nodes, check="diagnostics"):
                report = self.out(result)
                report.pop("meta", None)
                self.assertEqual(report, expected)

    def test_invalid_frontmatter_keeps_metadata_without_rendering_a_roadmap(self) -> None:
        """A computed graph with invalid metadata stays a diagnostic JSON result."""
        reference = f"{HOME}#1"
        body = fm(reference).replace(".type: feature", ".type: [invalid]")
        result = self.run_dag(
            {"home": HOME, "issues": {reference: issue(101, "Work", body)}},
            "--from-github",
            "--emit-roadmap",
        )
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        with self.subTest(check="invalid-metadata"):
            report = self.out(result)
            self.assertEqual(self.node(report, reference)["type"], ["invalid"])

    def test_valid_local_plan_still_renders_the_complete_diagram(self) -> None:
        """The successful variant preserves wave labels, node labels and reduced edges."""
        path = self.tmp / "spec.json"
        path.write_text(
            json.dumps(
                {
                    "nodes": {
                        "a": {"title": "A"},
                        "b": {"title": "B", "depends_on": ["a"]},
                    }
                }
            ),
            encoding="utf-8",
        )
        result = self.run_dag({}, "--verify-dag", str(path), "--emit-mermaid")
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with self.subTest(check="diagram"):
            self.assertEqual(
                result.stdout,
                "\n".join(
                    [
                        "flowchart TD",
                        '  subgraph Wave0["Wave 0: Open Frontier (Zero Incomplete Parents)"]',
                        '    N_a["a: A"]',
                        "  end",
                        '  subgraph Wave1["Wave 1"]',
                        '    N_b["b: B"]',
                        "  end",
                        "  N_a --> N_b",
                        "",
                    ]
                ),
            )
