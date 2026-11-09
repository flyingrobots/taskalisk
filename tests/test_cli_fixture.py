"""Keep test observations tied to actual response, state and command-log bytes."""

from __future__ import annotations

import json
from subprocess import CompletedProcess

from cli_fixture import Harness, TrustFixture


class CliFixture(TrustFixture):
    """The harness checks shapes without filling missing evidence with defaults."""

    def test_output_preserves_unknown_values_and_reports_invalid_json(self) -> None:
        """The decoder refuses syntax/container errors while retaining untyped leaves."""
        response = CompletedProcess(["fixture"], 2, '{"value": [false, null, 7]}', "detail")
        self.assertEqual(self.out(response), {"value": [False, None, 7]})
        response.stdout = "not-json"
        with self.assertRaisesRegex(AssertionError, r"not JSON \(exit 2\): not-json detail"):
            self.out(response)
        response.stdout = "[]"
        with self.assertRaisesRegex(TypeError, "fixture object"):
            self.out(response)

    def test_calls_preserve_order_and_require_text_arguments(self) -> None:
        """Blank log lines are harmless; malformed argv entries are evidence failures."""
        self.log.write_text('\n["api", "one"]\n  \n["api", "two", ""]\n')
        self.assertEqual(self.calls(), [["api", "one"], ["api", "two", ""]])
        self.log.write_text('{"command": "api"}\n')
        with self.assertRaisesRegex(TypeError, "fixture array"):
            self.calls()
        self.log.write_text('["api", 1]\n')
        with self.assertRaisesRegex(TypeError, "fixture text"):
            self.calls()

    def test_current_body_reads_persisted_state_and_requires_text(self) -> None:
        """Response contents cannot stand in for the separately persisted issue body."""
        self.state.write_text(json.dumps({"issues": {"owner/repo#1": {"body": "before"}}}))
        self.assertEqual(self.current_body("owner/repo#1"), "before")
        self.state.write_text(json.dumps({"issues": {"owner/repo#1": {"body": "after"}}}))
        self.assertEqual(self.current_body("owner/repo#1"), "after")
        self.state.write_text(json.dumps({"issues": {"owner/repo#1": {"body": 1}}}))
        with self.assertRaisesRegex(TypeError, "fixture text"):
            self.current_body("owner/repo#1")

    def test_wave_observations_do_not_invent_or_drop_nodes(self) -> None:
        """Identifiers are sorted across all waves; lookup returns the actual row."""
        report: dict[str, object] = {
            "waves": {"0": [{"id": "b", "value": [None]}], "1": [{"id": "a"}]}
        }
        self.assertEqual(Harness.ids(report), ["a", "b"])
        self.assertEqual(Harness.node(report, "b"), {"id": "b", "value": [None]})
        with self.assertRaises(StopIteration):
            Harness.node(report, "missing")
        with self.assertRaises(KeyError):
            Harness.ids({})
        with self.assertRaisesRegex(TypeError, "fixture text"):
            Harness.ids({"waves": {"0": [{"id": 1}]}})

    def test_untrusted_report_requires_recorded_identifiers(self) -> None:
        """An absent exclusion report cannot masquerade as an empty exclusion report."""
        report: dict[str, object] = {"source": {"untrusted_issues": [{"id": "b"}, {"id": "a"}]}}
        self.assertEqual(self.untrusted_ids(report), ["b", "a"])
        self.assertEqual(self.untrusted_ids({"source": {"untrusted_issues": []}}), [])
        with self.assertRaises(KeyError):
            self.untrusted_ids({"source": {}})
        with self.assertRaisesRegex(TypeError, "fixture text"):
            self.untrusted_ids({"source": {"untrusted_issues": [{"id": None}]}})
