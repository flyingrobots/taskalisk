"""Calibrate each source limit at its passing and failing boundary."""

from __future__ import annotations

import unittest

from tools.source_structure import measure_source
from tools.structure_limits import source_findings


class StructureLimits(unittest.TestCase):
    """Every upper bound has an independent refusal and a valid boundary control."""

    def rules(self, source: str, path: str = "tools/example.py") -> set[str]:
        """Read actual rule identifiers from parsed source, without faking measurements."""
        return {finding["rule"] for finding in source_findings(path, measure_source(source))}

    def test_locality_review_starts_above_three_hundred_lines(self) -> None:
        """The 200-line target does not silently become a hard limit."""
        self.assertNotIn("PY-FILE-LOCALITY", self.rules("value = 1\n" * 300))
        self.assertIn("PY-FILE-LOCALITY", self.rules("value = 1\n" * 301))

    def test_production_and_test_hard_ceilings_are_distinct(self) -> None:
        """Production is capped at 500 lines; test code is capped at 750."""
        for path, limit in (("tools/example.py", 500), ("tests/test_example.py", 750)):
            with self.subTest(path=path):
                self.assertNotIn("PY-FILE-HARD", self.rules("value = 1\n" * limit, path))
                self.assertIn("PY-FILE-HARD", self.rules("value = 1\n" * (limit + 1), path))

    def test_function_lines_and_review_threshold_are_independent(self) -> None:
        """Forty-one lines need review; sixty-one also exceed the function limit."""
        cases: tuple[tuple[int, set[str]], ...] = (
            (40, set()),
            (41, {"PY-FUNCTION-REVIEW"}),
            (60, {"PY-FUNCTION-REVIEW"}),
            (61, {"PY-FUNCTION-REVIEW", "PY-FUNCTION-LINES"}),
        )
        for lines, expected in cases:
            with self.subTest(lines=lines):
                self.assertEqual(self.rules("def work():\n" + "    operate()\n" * lines), expected)

    def test_nesting_refuses_four_scopes_and_accepts_three(self) -> None:
        """An additional conditional expression crosses the independent nesting bound."""
        prefix = "def work(xs):\n    for x in xs:\n        if x:\n            with resource():\n"
        self.assertNotIn("PY-FUNCTION-NESTING", self.rules(prefix + "                consume(x)\n"))
        self.assertIn(
            "PY-FUNCTION-NESTING", self.rules(prefix + "                consume(1 if x else 0)\n")
        )

    def test_six_semantic_parameters_are_refused(self) -> None:
        """The maximum remains five even when a signature is formatted compactly."""
        self.assertNotIn("PY-FUNCTION-PARAMETERS", self.rules("def work(a, b, c, d, e): pass\n"))
        self.assertIn("PY-FUNCTION-PARAMETERS", self.rules("def work(a, b, c, d, e, f): pass\n"))

    def test_four_field_anonymous_returns_are_refused(self) -> None:
        """A fourth positional result needs a named record instead of a larger tuple."""
        self.assertNotIn("PY-FUNCTION-TUPLE", self.rules("def work(): return 1, 2, 3\n"))
        self.assertIn("PY-FUNCTION-TUPLE", self.rules("def work(): return 1, 2, 3, 4\n"))

    def test_findings_identify_the_exact_source_and_symbol(self) -> None:
        """A reviewer must be able to locate and understand the rejected measurement."""
        result = source_findings(
            "tools/example.py", measure_source("\ndef work(a, b, c, d, e, f): pass\n")
        )
        self.assertEqual(
            result,
            [
                {
                    "path": "tools/example.py",
                    "symbol": "work",
                    "line": 2,
                    "rule": "PY-FUNCTION-PARAMETERS",
                    "observed": 6,
                    "limit": 5,
                }
            ],
        )
