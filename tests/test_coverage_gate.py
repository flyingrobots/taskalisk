"""Check the coverage gate using independent counter examples and real files."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.check_coverage import object_fields, read_counts

CHECKER = Path(__file__).resolve().parents[1] / "tools" / "check_coverage.py"
CRITICAL = (
    "authorization",
    "identities",
    "frontmatter",
    "issue_refs",
    "github",
    "discovery",
    "process",
    "modes",
    "spec_checks",
    "spec_file",
    "spec_values",
)
PREFIX = "skills/taskalisk/scripts/taskalisk_core/"


def counters(lines: int = 100, branches: int = 100) -> dict[str, int]:
    """Construct independent one-hundred-count percentages without rounding."""
    return {
        "num_statements": 100,
        "covered_lines": lines,
        "missing_lines": 100 - lines,
        "num_branches": 100,
        "covered_branches": branches,
        "missing_branches": 100 - branches,
    }


class CoverageGate(unittest.TestCase):
    """A healthy aggregate must not hide a deficient or missing component."""

    def setUp(self) -> None:
        """Give each invocation a small, disposable repository and report."""
        self.temporary = tempfile.TemporaryDirectory(prefix="taskalisk-coverage-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.summaries = {f"{PREFIX}{name}.py": counters() for name in CRITICAL}
        self.summaries[f"{PREFIX}graph.py"] = counters()
        for filename in self.summaries:
            target = self.root / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("pass\n", encoding="utf-8")

    def invoke(self, report: object) -> subprocess.CompletedProcess[str]:
        """Run the public checker against a real JSON file with a deadline."""
        path = self.root / "report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return self.invoke_path(path)

    def invoke_path(self, path: Path) -> subprocess.CompletedProcess[str]:
        """Run a fixed checker over a supplied, owned report path."""
        # policy-exception: PY-COVERAGE-ARGV -- Fixed checker; only owned fixture paths vary.
        return subprocess.run(  # noqa: S603
            [sys.executable, str(CHECKER), "--root", str(self.root), str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    def report(self) -> dict[str, object]:
        """Wrap the counters in Coverage.py's public JSON report shape."""
        return {
            "meta": {"branch_coverage": True},
            "files": {path: {"summary": value} for path, value in self.summaries.items()},
        }

    def assert_refused(self, report: object, diagnostic: str) -> None:
        """Check both refusal and cause, even when the first assertion fails."""
        result = self.invoke(report)
        self.assert_rejected(result, diagnostic)

    def assert_rejected(self, result: subprocess.CompletedProcess[str], diagnostic: str) -> None:
        """Keep exit-status and diagnostic failures independently observable."""
        with self.subTest(check="refusal"):
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        with self.subTest(check="diagnostic"):
            self.assertIn(diagnostic, result.stdout + result.stderr)

    def test_critical_statement_and_branch_floors_are_separate(self) -> None:
        """A 97% combined score cannot hide a 94% critical measure."""
        path = f"{PREFIX}authorization.py"
        for measure, value in [("statements", counters(94, 100)), ("branches", counters(100, 94))]:
            with self.subTest(measure=measure):
                self.summaries[path] = value
                self.assert_refused(self.report(), f"{path}: {measure} 94/100 below 95%")

    def test_ordinary_component_uses_the_ninety_percent_floor(self) -> None:
        """An ordinary module cannot borrow coverage from another component."""
        path = f"{PREFIX}graph.py"
        self.summaries[path] = counters(89, 100)
        self.assert_refused(self.report(), f"{path}: statements 89/100 below 90%")

    def test_local_spec_admission_receives_the_critical_floor(self) -> None:
        """File, scalar and domain admission each need independent 95% coverage."""
        for module in ("spec_checks", "spec_file", "spec_values"):
            path = f"{PREFIX}{module}.py"
            with self.subTest(module=module):
                self.summaries[path] = counters(94, 100)
                self.assert_refused(self.report(), f"{path}: statements 94/100 below 95%")
            self.summaries[path] = counters()

    def test_discovery_admission_and_its_helpers_receive_the_critical_floor(self) -> None:
        """Moving scope and trust decisions cannot lower their verification requirement."""
        for module in ("discovery", "discovery_admission", "discovery_walk"):
            path = f"{PREFIX}{module}.py"
            (self.root / path).write_text("pass\n", encoding="utf-8")
            with self.subTest(module=module):
                self.summaries[path] = counters(100, 94)
                self.assert_refused(self.report(), f"{path}: branches 94/100 below 95%")
            self.summaries[path] = counters()

    def test_missing_component_cannot_disappear_from_the_report(self) -> None:
        """A source file missing from measurement fails closed."""
        path = f"{PREFIX}authorization.py"
        del self.summaries[path]
        self.assert_refused(self.report(), f"{path}: missing coverage")

    def test_uninstrumented_subprocess_code_fails_the_floor(self) -> None:
        """Parent-process test execution cannot stand in for CLI execution."""
        path = f"{PREFIX}authorization.py"
        self.summaries[path] = counters(0, 0)
        self.assert_refused(self.report(), f"{path}: statements 0/100 below 95%")

    def test_empty_measurement_cannot_hide_executable_source(self) -> None:
        """Zero opportunities are invalid when the source contains executable code."""
        path = f"{PREFIX}authorization.py"
        self.summaries[path] = dict.fromkeys(counters(), 0)
        self.assert_refused(self.report(), f"{path}: no statements measured for executable source")

    def test_validation_tools_receive_the_critical_floor(self) -> None:
        """The gate itself must meet the validation-component coverage requirement."""
        (self.root / "tools").mkdir()
        for name in ("check_coverage", "source_structure", "structure_limits"):
            path = f"tools/{name}.py"
            (self.root / path).write_text("pass\n", encoding="utf-8")
            self.summaries[path] = counters(94, 100)
            self.assert_refused(self.report(), f"{path}: statements 94/100 below 95%")
            self.summaries[path] = counters()

    def test_rounded_percentage_cannot_meet_a_floor(self) -> None:
        """A value rounded to 95.00% still fails when its exact ratio is lower."""
        path = f"{PREFIX}authorization.py"
        self.summaries[path].update(num_statements=100000, covered_lines=94999, missing_lines=5001)
        self.assert_refused(self.report(), f"{path}: statements 94999/100000 below 95%")

    def test_wrong_shape_or_missing_branch_measurement_is_refused(self) -> None:
        """Absent report structure and statement-only data are not success."""
        invalid_reports: list[object] = [
            None,
            [],
            {},
            {"meta": {"branch_coverage": False}, "files": {}},
        ]
        for report in invalid_reports:
            with self.subTest(report=report):
                self.assert_refused(report, "invalid coverage report")

    def test_impossible_or_non_integer_counts_are_refused(self) -> None:
        """Malformed counts cannot manufacture a passing percentage."""
        path = f"{PREFIX}authorization.py"
        for bad in [-1, 101, True, 99.9, "100"]:
            with self.subTest(count=bad):
                report = self.report()
                malformed: dict[str, object] = dict(counters())
                malformed["covered_lines"] = bad
                report["files"] = {path: {"summary": malformed}}
                self.assert_refused(report, f"{path}: invalid counts")

    def test_exact_thresholds_and_branchless_files_pass(self) -> None:
        """Valid boundary values and genuine zero-branch files stay usable."""
        self.summaries[f"{PREFIX}authorization.py"] = counters(95, 95)
        branchless = counters(90, 100)
        branchless.update(num_branches=0, covered_branches=0, missing_branches=0)
        self.summaries[f"{PREFIX}graph.py"] = branchless
        result = self.invoke(self.report())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_invalid_object_and_summary_boundaries_refuse_values(self) -> None:
        """Public object decoders reject non-string keys and non-object counts."""
        with self.subTest(boundary="object keys"):
            self.assertIsNone(object_fields({1: "not a JSON key"}))
        with self.subTest(boundary="counts container"):
            self.assertIsNone(read_counts(None))

    def test_missing_required_source_does_not_pass_from_old_measurement(self) -> None:
        """A retained report cannot cover a required module that is absent now."""
        path = f"{PREFIX}authorization.py"
        (self.root / path).unlink()
        self.assert_refused(self.report(), f"{path}: required source is missing")

    def test_invalid_source_prevents_accepting_a_zero_statement_count(self) -> None:
        """A failed source inspection cannot justify an empty measurement."""
        path = f"{PREFIX}authorization.py"
        (self.root / path).write_text("def (", encoding="utf-8")
        self.summaries[path] = dict.fromkeys(counters(), 0)
        self.assert_refused(self.report(), f"{path}: cannot inspect source")

    def test_missing_and_malformed_report_files_are_refused(self) -> None:
        """Real file and JSON failures remain explicit unsuccessful results."""
        missing = self.root / "missing.json"
        malformed = self.root / "malformed.json"
        malformed.write_text("{", encoding="utf-8")
        for path in [missing, malformed]:
            with self.subTest(path=path.name):
                self.assert_rejected(self.invoke_path(path), "invalid coverage report")

    def test_docstring_only_module_allows_zero_statement_opportunities(self) -> None:
        """An empty module is distinct from executable but unmeasured code."""
        path = f"{PREFIX}authorization.py"
        (self.root / path).write_text(
            '"""A module without executable statements."""\n', encoding="utf-8"
        )
        self.summaries[path] = dict.fromkeys(counters(), 0)
        result = self.invoke(self.report())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
