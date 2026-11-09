"""Require bounded, typed local DAG input through the public CLI."""

from __future__ import annotations

import json
import os
import sys

from cli_fixture import SCRIPT, Harness
from fake_values import field

from skills.taskalisk.scripts.taskalisk_core.process import run_cmd_checked
from skills.taskalisk.scripts.taskalisk_core.process_limits import CommandLimits


class SpecCli(Harness):
    """Malformed local planning data must not crash or silently change dependencies."""

    def assert_spec_refusal(self, raw: bytes, diagnostic: str) -> None:
        """Require a structured validation exit with no admitted graph."""
        path = self.tmp / "spec.json"
        path.write_bytes(raw)
        result = self.run_dag({}, "--verify-dag", str(path))
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        with self.subTest(check="diagnostic"):
            self.assertIn(diagnostic, result.stdout)
        with self.subTest(check="no-plan"):
            self.assertNotIn("waves", self.out(result))

    def test_malformed_graph_fields_have_structured_refusals(self) -> None:
        """Bad node, dependency and resource shapes cannot become partial plans."""
        cases: tuple[tuple[object, str], ...] = (
            ({"nodes": {"a": []}}, "node a must be an object"),
            ({"merged": True}, "merged must be an array"),
            (
                {"nodes": {"A": {}, "B": {}, "C": {"depends_on": "AB"}}},
                "depends_on must be an array",
            ),
            (
                {"nodes": {"a": {}, "b": {"depends_on": [{"from": "a", "isHard": "false"}]}}},
                "isHard must be a Boolean",
            ),
            (
                {"nodes": {"a": {}, "b": {"depends_on": [{"from": "a", "confidence": "0.1"}]}}},
                "confidence must be a number",
            ),
            ({"nodes": {"a": {"holds": ["lock", False]}}}, "holds entry must be text"),
        )
        for value, diagnostic in cases:
            with self.subTest(value=value):
                self.assert_spec_refusal(json.dumps(value).encode(), diagnostic)

    def test_ambiguous_json_cannot_hide_a_node_or_dependency(self) -> None:
        """The local spec uses the same duplicate-key and nonfinite-number refusal as GitHub."""
        for raw, diagnostic in (
            (b'{"nodes":{"a":{},"a":{}}}', "duplicate object key"),
            (b'{"nodes":{"a":{"size_hours":NaN}}}', "non-finite number"),
            (b'{"nodes":{},"extra":"\\ud800"}', "invalid Unicode scalar"),
        ):
            with self.subTest(diagnostic=diagnostic):
                self.assert_spec_refusal(raw, diagnostic)

    def test_file_read_has_a_byte_ceiling(self) -> None:
        """Oversized otherwise valid input is refused before complete JSON decoding."""
        raw = b'{"nodes":{},"extra":"' + b"x" * (32 * 1024 * 1024) + b'"}'
        self.assert_spec_refusal(raw, "exceeds 33554432 bytes")

    def test_invalid_utf8_is_a_structured_input_error(self) -> None:
        """A decoding error cannot escape as an unstructured traceback."""
        self.assert_spec_refusal(b"\xff", "Cannot read DAG spec")

    def test_fifo_is_refused_without_waiting_for_a_writer(self) -> None:
        """Only regular files are supported; the witness itself has a one-second deadline."""
        path = self.tmp / "spec.fifo"
        os.mkfifo(path)
        _, output, error = run_cmd_checked(
            [sys.executable, str(SCRIPT), "--verify-dag", str(path)],
            cwd=str(self.repo),
            limits=CommandLimits(timeout_seconds=1),
        )
        self.assertIn("regular file", output, error)

    def test_valid_aliases_and_merged_hints_keep_the_plan(self) -> None:
        """Legacy aliases and arbitrary textual IDs retain their planning meaning."""
        path = self.tmp / "spec.json"
        path.write_text(
            json.dumps(
                {
                    "merged": ["past (merged)"],
                    "nodes": {
                        "first": {
                            "title": "First",
                            "resources": ["disk"],
                            "prerequisites": ["past"],
                        },
                        "second": {"title": "Second", "depends_on": [{"from": "first"}]},
                    },
                }
            ),
            encoding="utf-8",
        )
        result = self.run_dag({}, "--verify-dag", str(path))
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = self.out(result)
        with self.subTest(check="critical-path"):
            self.assertEqual(field(report, "metrics", "critical_path"), ["first", "second"])
        with self.subTest(check="completed-parent"):
            self.assertEqual(self.node(report, "first")["completed_parents"], ["past"])
        with self.subTest(check="resources"):
            self.assertEqual(self.node(report, "first")["holds"], ["disk"])
        with self.subTest(check="offline"):
            self.assertEqual(self.calls(), [])
