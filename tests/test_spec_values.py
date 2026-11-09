"""Exercise local graph admission independently of filesystem and CLI behavior."""

from __future__ import annotations

import unittest

from skills.taskalisk.scripts.taskalisk_core.spec_values import parse_spec


class SpecValues(unittest.TestCase):
    """Consumed data must be checked without narrowing valid planning conventions."""

    def test_empty_spec_and_default_node(self) -> None:
        """An empty plan and an unnamed task retain their established defaults."""
        with self.subTest(plan="empty"):
            self.assertEqual(parse_spec({}), {"merged": set(), "nodes": {}})
        with self.subTest(plan="default-node"):
            self.assertEqual(
                parse_spec({"nodes": {"hand written / ID": {}}}),
                {
                    "merged": set(),
                    "nodes": {
                        "hand written / ID": {
                            "title": "",
                            "url": None,
                            "milestone": None,
                            "in_filter": True,
                            "type": "",
                            "workstream": "",
                            "status": "open",
                            "size_hours": None,
                            "depends_on": [],
                            "holds": [],
                            "meters": [],
                            "linked_open_prs": [],
                            "recoverable_branches": [],
                            "opaque": False,
                            "untrusted": False,
                        }
                    },
                },
            )

    def test_explicit_values_survive_admission(self) -> None:
        """All consumed metadata, resource and dependency values retain their meaning."""
        node = {
            "title": "Work",
            "url": "https://example.test/task",
            "milestone": "M1",
            "in_filter": False,
            "type": "experiment",
            "workstream": "alpha",
            "status": "parked",
            "size_hours": 3,
            "depends_on": [
                "ancestor (merged)",
                {
                    "from": "parent",
                    "type": "inferred",
                    "isHard": False,
                    "confidence": 0.5,
                    "evidence": "operator judgment",
                },
            ],
            "holds": ["repo/src/"],
            "meters": [{"name": "workers", "slots": 2}],
            "linked_open_prs": [{"number": 8, "isDraft": True, "url": "https://example.test/pr"}],
            "recoverable_branches": ["task/8"],
            "opaque": True,
            "untrusted": True,
        }
        self.assertEqual(
            parse_spec({"merged": ["old (merged)"], "nodes": {"work": node}}),
            {"merged": {"old"}, "nodes": {"work": node}},
        )

    def test_alias_precedence_null_resources_and_dependency_defaults(self) -> None:
        """Primary keys win even when empty, and nullable resources remain empty."""
        result = parse_spec(
            {
                "nodes": {
                    "primary": {
                        "depends_on": [],
                        "prerequisites": False,
                        "holds": None,
                        "resources": False,
                        "meters": None,
                    },
                    "aliases": {
                        "prerequisites": [{"from": "old"}],
                        "resources": ["disk"],
                        "linked_open_prs": [{"number": 2}],
                    },
                }
            }
        )
        primary, aliases = result["nodes"]["primary"], result["nodes"]["aliases"]
        for field in ("depends_on", "holds", "meters"):
            with self.subTest(field=field):
                self.assertEqual(primary.get(field), [])
        with self.subTest(field="dependency-defaults"):
            self.assertEqual(
                aliases.get("depends_on"),
                [
                    {
                        "from": "old",
                        "type": "accepted",
                        "isHard": True,
                        "confidence": 1.0,
                        "evidence": "Declared in DAG specification",
                    }
                ],
            )
        with self.subTest(field="resource-alias"):
            self.assertEqual(aliases.get("holds"), ["disk"])
        with self.subTest(field="PR-defaults"):
            self.assertEqual(
                aliases.get("linked_open_prs"), [{"number": 2, "isDraft": False, "url": None}]
            )

    def test_refuses_wrong_root_node_and_merged_shapes(self) -> None:
        """No malformed container, key or merged name can become an empty valid graph."""
        cases: list[object] = [
            None,
            [],
            {1: {}},
            {"nodes": []},
            {"nodes": {"a": []}},
            {"nodes": {" ": {}}},
            {"merged": None},
            {"merged": [False]},
            {"merged": [""]},
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                parse_spec(value)

    def test_refuses_malformed_metadata_and_resources(self) -> None:
        """Refuse scalar coercion and malformed later entries, including nullable arrays."""
        cases: tuple[tuple[str, object], ...] = (
            ("title", False),
            ("url", 3),
            ("milestone", []),
            ("in_filter", "true"),
            ("type", []),
            ("workstream", 2),
            ("status", None),
            ("size_hours", True),
            ("size_hours", 0),
            ("size_hours", "2"),
            ("opaque", 1),
            ("untrusted", None),
            ("holds", "lock"),
            ("holds", ["valid", False]),
            ("holds", [" "]),
            ("resources", {}),
            ("meters", {}),
            ("meters", [False]),
            ("meters", [{"name": "workers", "slots": True}]),
            ("meters", [{"name": "workers", "slots": 1.5}]),
            ("meters", [{"name": "", "slots": 1}]),
            ("meters", [{"name": "workers"}]),
            ("recoverable_branches", None),
            ("recoverable_branches", ["valid", 3]),
            ("linked_open_prs", None),
            ("linked_open_prs", [False]),
            ("linked_open_prs", [{"number": True}]),
            ("linked_open_prs", [{"number": 2, "isDraft": "false"}]),
            ("linked_open_prs", [{"number": 2, "url": False}]),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaises((TypeError, ValueError)):
                parse_spec({"nodes": {"first": {}, "bad": {field: value}}})

    def test_refuses_malformed_dependencies(self) -> None:
        """Edges cannot silently disappear or change hardness through coercion."""
        cases: list[object] = [
            "ab",
            None,
            [False],
            [""],
            [{}],
            [{"from": 3}],
            [{"from": " "}],
            [{"from": "a", "type": False}],
            [{"from": "a", "isHard": "false"}],
            [{"from": "a", "evidence": []}],
            [{"from": "a", "confidence": True}],
            [{"from": "a", "confidence": "0.5"}],
            [{"from": "a", "confidence": -1}],
            [{"from": "a", "confidence": 2}],
            [{"from": "a", "confidence": float("nan")}],
            [{"from": "a", "confidence": float("inf")}],
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                parse_spec({"nodes": {"b": {"depends_on": value}}})

    def test_confidence_endpoints_are_valid_numbers(self) -> None:
        """Zero and one remain usable confidence values without Boolean admission."""
        for confidence in (0, 1):
            with self.subTest(confidence=confidence):
                result = parse_spec(
                    {"nodes": {"b": {"depends_on": [{"from": "a", "confidence": confidence}]}}}
                )
                self.assertEqual(
                    result["nodes"]["b"].get("depends_on"),
                    [
                        {
                            "from": "a",
                            "type": "accepted",
                            "isHard": True,
                            "confidence": float(confidence),
                            "evidence": "Declared in DAG specification",
                        }
                    ],
                )
