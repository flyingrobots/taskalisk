"""Verify malformed GitHub bytes become structured CLI errors, never a partial plan."""

from __future__ import annotations

import json
from typing import cast

from cli_fixture import Harness


class GithubJsonCli(Harness):
    """The adapter's JSON rejection must reach the public command's exit status."""

    def test_bad_listing_bytes_refuse_the_run_with_exit_two(self) -> None:
        """Empty output, invalid rows and ambiguous pages cannot hide issues."""
        cases = [
            ("", "empty response"),
            ("[null]", "Expected a JSON array of objects"),
            ('[]\n[{"number":1,"number":2}]', "duplicate object key"),
            ("[]\n[null]", "Expected a JSON array of objects"),
        ]
        for raw, diagnostic in cases:
            with self.subTest(raw=raw):
                state: dict[str, object] = {
                    "home": "org/repo",
                    "issues": {},
                    "blocked_by": {},
                    "issues_list_raw": raw,
                }
                result = self.run_dag(state, "--from-github")
                with self.subTest(check="exit"):
                    self.assertEqual(result.returncode, 2, result.stdout)
                decoded: object = json.loads(result.stdout)
                self.assertIsInstance(decoded, dict, "CLI error must be a JSON object")
                # The preceding assertion checks dict; no field type is claimed.
                fields = cast("dict[object, object]", decoded)
                with self.subTest(check="refusal"):
                    expected_ok = False
                    self.assertIs(fields.get("ok"), expected_ok)
                with self.subTest(check="diagnostic"):
                    self.assertIn(diagnostic, result.stdout)

    def test_actual_empty_array_is_a_successful_empty_backlog(self) -> None:
        """The command distinguishes an empty response from an empty issue array."""
        state: dict[str, object] = {
            "home": "org/repo",
            "issues": {},
            "blocked_by": {},
            "issues_list_raw": "[]",
        }
        result = self.run_dag(state, "--from-github")
        self.assertEqual(result.returncode, 0, result.stdout)
