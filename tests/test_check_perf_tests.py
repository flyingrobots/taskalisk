"""scripts/check_perf_tests.py: the release perf job fails unless every perf_ test that exists ran and
passed (flyingrobots/taskalisk#120)."""
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_perf_tests", ROOT / "scripts" / "check_perf_tests.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

CORE = "     Running unittests src/lib.rs (target/release/build/issue-dag-core/28df/out/issue_dag_core-28df)"
BUNDLE = "     Running tests/load.rs (target/release/build/issue-dag-bundle/8295/out/load-8295)"
SIX = [
    "batch::scale::perf_a_chain_of_5000_nodes_ranks_and_selects_within_the_bound",
    "batch::scale::perf_a_fan_of_5000_nodes_ranks_within_the_bound",
    "batch::scale::perf_a_wide_frontier_of_5000_nodes_ranks_and_selects_within_the_bound",
    "plan::tests::perf_a_chain_of_5000_tasks_plans_within_the_bound",
    "plan::tests::perf_a_wide_graph_of_5000_tasks_plans_within_the_bound",
    "plan::tests::perf_g4_a_long_cycle_is_reported_within_the_bound",
]


def listed(names, binary=CORE):
    """`cargo test -- --ignored --list perf_` output for one test binary, as cargo prints it."""
    lines = [BUNDLE, "0 tests, 0 benchmarks", binary]
    lines += ["{}: test".format(n) for n in names]
    lines.append("{} tests, 0 benchmarks".format(len(names)))
    return "\n".join(lines) + "\n"


def ran(results, binary=CORE):
    """The run's output: `results` maps a test name to ok, FAILED or ignored."""
    lines = ["   Compiling issue-dag-core v0.1.0", BUNDLE, "running 0 tests", binary,
             "running {} tests".format(len(results))]
    lines += ["test {} ... {}".format(n, r) for n, r in results.items()]
    lines.append("test result: ok. {} passed; 0 failed".format(sum(r == "ok" for r in results.values())))
    return "\n".join(lines) + "\n"


class CheckPerfTests(unittest.TestCase):
    def test_every_listed_test_passing_passes_and_reports_the_count(self):
        ok, message = checker.check(listed(SIX), ran({n: "ok" for n in SIX}))
        self.assertTrue(ok, message)
        self.assertIn("perf_ tests passed: 6 of 6", message)

    def test_a_listed_test_that_did_not_run_fails_and_is_named(self):
        # F-1 of Baker Street case 2026-11-26-taskalisk-pr116-delta: a seventh test exists, six pass.
        seventh = "plan::tests::perf_a_seventh_bound"
        ok, message = checker.check(listed(SIX + [seventh]), ran({n: "ok" for n in SIX}))
        self.assertFalse(ok, message)
        self.assertIn(seventh, message)

    def test_no_listed_test_fails(self):
        ok, message = checker.check(listed([]), ran({}))
        self.assertFalse(ok, message)

    def test_zero_passed_fails_and_still_reports_the_count(self):
        # F-2: the count is printed even when nothing passed.
        ok, message = checker.check(listed(SIX), ran({}))
        self.assertFalse(ok, message)
        self.assertIn("perf_ tests passed: 0 of 6", message)

    def test_failed_or_ignored_lines_never_count_as_passed(self):
        results = {n: "ok" for n in SIX}
        results[SIX[0]] = "FAILED"
        results[SIX[1]] = "ignored, wall-clock bound; run with --release --ignored"
        ok, message = checker.check(listed(SIX), ran(results))
        self.assertFalse(ok, message)
        self.assertIn(SIX[0], message)
        self.assertIn(SIX[1], message)

    def test_the_same_name_in_another_test_binary_is_a_different_test(self):
        name = "tests::perf_shared_name"
        both = listed([name]) + listed([name], binary=BUNDLE)
        ok, message = checker.check(both, ran({name: "ok"}))
        self.assertFalse(ok, message)
        self.assertIn("load", message)

    def test_main_prints_the_count_and_exits_by_the_outcome(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            listed_path = pathlib.Path(tmp, "listed.log")
            ran_path = pathlib.Path(tmp, "ran.log")
            listed_path.write_text(listed(SIX), encoding="utf-8")
            for results, want in (({n: "ok" for n in SIX}, 0), ({}, 1)):
                ran_path.write_text(ran(results), encoding="utf-8")
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = checker.main([str(listed_path), str(ran_path)])
                self.assertEqual(code, want, out.getvalue())
                self.assertIn("perf_ tests passed:", out.getvalue())


class PerfJob(unittest.TestCase):
    """The workflow step that runs the check."""

    def step(self):
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        start = workflow.index("- name: Wall-clock bounds of large graphs")
        return workflow[start:]

    def test_the_step_runs_the_check_and_hardcodes_no_count(self):
        step = self.step()
        self.assertIn("python3 scripts/check_perf_tests.py perf-listed.log perf.log", step)
        self.assertNotRegex(step, r"-ge\s+\d")

    def test_the_list_includes_tests_that_lost_their_ignore(self):
        # Listing with --ignored would drop a perf_ test whose #[ignore] was removed: it would
        # leave the release run and flake in the default suite with nothing to notice.
        step = self.step()
        self.assertIn("-- --list perf_ > perf-listed.log 2>&1", step)
        self.assertIn("-- --ignored perf_ 2>&1 | tee perf.log", step)

    def test_a_failing_cargo_test_fails_the_step(self):
        # The run is piped through tee; only pipefail, which `shell: bash` sets, keeps its status.
        self.assertIn("shell: bash", self.step())


class PerfNames(unittest.TestCase):
    """The job finds the bounds by the name filter perf_, so a bound renamed out of it would leave
    the run unseen. Every test ignored as a wall-clock bound is named perf_, and every perf_ test is
    ignored as one."""

    # The attributes before a fn, and its name.
    ITEM = re.compile(r"((?:[ \t]*#\[[^\n]*\][ \t]*\n)+)[ \t]*(?:pub(?:\([^)]*\))?\s+)?fn\s+(\w+)")
    MARK = '#[ignore = "wall-clock bound'

    def items(self):
        for path in sorted((ROOT / "crates").rglob("*.rs")):
            text = path.read_text(encoding="utf-8")
            for attributes, name in self.ITEM.findall(text):
                yield path.relative_to(ROOT), attributes, name

    def test_bounds_and_perf_names_agree(self):
        marked = {(p, n) for p, a, n in self.items() if self.MARK in a}
        named = {(p, n) for p, a, n in self.items() if n.startswith("perf_")}
        self.assertTrue(marked, "no test is ignored as a wall-clock bound")
        self.assertEqual(marked, named)


if __name__ == "__main__":
    unittest.main()
