"""Preserve dependency classifications and readable reduced-graph presentations."""

import json

from cli_fixture import HOME, Harness, fm, issue
from fake_values import field


class PlanPresentations(Harness):
    """Concrete examples keep ignored dependencies and redundant evidence distinguishable."""

    def test_soft_and_repeated_completed_dependencies_preserve_the_plan(self) -> None:
        """Soft/low-confidence references stay visible without blocking; completed parents deduplicate."""
        path = self.tmp / "dependencies.json"
        path.write_text(
            json.dumps(
                {
                    "merged": ["past"],
                    "nodes": {
                        "work": {
                            "depends_on": [
                                "past",
                                "past (merged)",
                                {"from": "advice", "isHard": False, "evidence": "optional"},
                                {"from": "uncertain", "confidence": 0.1, "evidence": "weak"},
                            ]
                        }
                    },
                }
            )
        )
        result = self.run_dag({}, "--verify-dag", str(path))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.out(result)
        self.assertEqual(self.ids(report), ["work"])
        self.assertEqual(self.node(report, "work")["completed_parents"], ["past"])
        self.assertEqual(report["edges"], [])
        self.assertEqual(
            report["soft_or_low_confidence_edges"],
            [
                {
                    "from": "advice",
                    "to": "work",
                    "type": "accepted",
                    "isHard": False,
                    "confidence": 1.0,
                    "evidence": "optional",
                },
                {
                    "from": "uncertain",
                    "to": "work",
                    "type": "accepted",
                    "isHard": True,
                    "confidence": 0.1,
                    "evidence": "weak",
                },
            ],
        )
        self.assertEqual(self.calls(), [])

    def test_roadmap_keeps_redundant_edge_evidence_and_bounds_mermaid_titles(self) -> None:
        """Reduction removes a redundant diagram edge but retains its explicit evidence."""
        title = "Long " + "x" * 60
        one, two, three = (f"{HOME}#{number}" for number in (1, 2, 3))
        state = {
            "home": HOME,
            "blocked_by": {},
            "issues": {
                one: issue(101, title, fm(one)),
                two: issue(102, "Two", fm(two, blocked_by=[one])),
                three: issue(103, "Three", fm(three, blocked_by=[one, two])),
            },
        }
        result = self.run_dag(state, "--from-github", "--emit-roadmap")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        diagram = result.stdout.split("```mermaid\n", 1)
        self.assertEqual(len(diagram), 2, result.stdout)
        mermaid = diagram[1].split("```", 1)[0]
        self.assertIn(f"{one}: {title[:45]}...", mermaid)
        self.assertNotIn(title, mermaid)
        self.assertIn(title, result.stdout.split("```mermaid\n", 1)[0])
        self.assertNotIn("N_flyingrobots_geordi_1 --> N_flyingrobots_geordi_3", mermaid)
        self.assertIn(f"- {one} → {three} (via {two})", result.stdout)

    def test_edge_without_a_separator_refuses_before_any_provider_call(self) -> None:
        """Malformed edge syntax cannot trigger repository discovery or a remote edit."""
        result = self.run_dag({}, "--from-github", "--add-edge", f"{HOME}#1")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIs(field(self.out(result), "ok"), expr2=False)
        self.assertEqual(self.calls(), [])
