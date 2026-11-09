"""Check operator option refusal before provider calls and preserve output precedence."""

from cli_fixture import HOME, Harness, fm
from fake_values import field, records
from test_discovery_order import two_seeds


class CliOptions(Harness):
    """Option validation must finish before a provider request or remote effect."""

    def test_invalid_option_combinations_stop_before_provider_calls(self) -> None:
        """Every declared incompatibility produces argparse exit 2 without consulting GitHub."""
        edge = f"{HOME}#1->{HOME}#2"
        cases = [
            (["--add-edge", edge], "--add-edge/--remove-edge require --from-github"),
            (["--from-github", "--add-edge", edge, "--remove-edge", edge], "mutually exclusive"),
            (["--emit-roadmap"], "--emit-roadmap requires --from-github"),
            (["--from-github", "--verify-dag", "unused.json"], "mutually exclusive"),
            (["--sem-capacity", "cpu=0"], "--sem-capacity takes name=N with N >= 1"),
            (["--sem-capacity", "=2"], "--sem-capacity takes name=N with N >= 1"),
            (["--sem-capacity", "cpu=bad"], "--sem-capacity takes name=N with N >= 1"),
            (["--root", f"{HOME}#1"], "--root and --compare-relationships require --from-github"),
            (["--compare-relationships"], "require --from-github"),
            (
                ["--trust", "owner"],
                "--trust, --trust-owner, --trust-repo and --trust-codeowners require --from-github",
            ),
            (["--from-github", "--trust-owner", "bad/owner"], "--trust-owner takes an owner name"),
            (["--from-github", "--trust-repo", "bad"], "--trust-repo takes owner/repo"),
        ]
        for arguments, diagnostic in cases:
            with self.subTest(arguments=arguments):
                process = self.run_dag(two_seeds(), *arguments)
                self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
                self.assertEqual(process.stdout, "")
                self.assertIn(diagnostic, process.stderr)
                self.assertEqual(self.calls(), [])

    def test_last_capacity_value_reaches_the_frontier_allocator(self) -> None:
        """The last repeated capacity permits the two-slot task and excludes the competitor."""
        state = two_seeds()
        for number in (1, 2):
            state["issues"][f"{HOME}#{number}"]["body"] = fm(
                f"{HOME}#{number}", extra=".meters: [cpu*2]"
            )
        process = self.run_dag(
            state, "--from-github", "--sem-capacity", "cpu=1", "--sem-capacity", "cpu=2"
        )
        result = self.out(process)
        self.assertEqual(process.returncode, 0, result)
        self.assertEqual(
            [node["id"] for node in records(field(result, "conflict_free_frontier_batch"))],
            [f"{HOME}#1"],
        )
        self.assertEqual(field(result, "semaphores_with_unknown_capacity_treated_as_1"), [])

    def test_roadmap_wins_when_both_render_flags_are_present(self) -> None:
        """Both permitted flags retain the documented roadmap wrapper around the graph."""
        process = self.run_dag(two_seeds(), "--from-github", "--emit-mermaid", "--emit-roadmap")
        self.assertEqual(process.returncode, 0, process.stdout)
        self.assertTrue(process.stdout.startswith("<!-- BEGIN GENERATED ISSUE DAG"))
        self.assertTrue(process.stdout.endswith("<!-- END GENERATED ISSUE DAG -->\n"))

    def test_codeowners_option_admits_named_people_without_inventing_teams(self) -> None:
        """The parsed trust option reaches authorization and retains only observed evidence."""
        state = two_seeds()
        state["issues"][f"{HOME}#1"].update(author="maintainer", association="NONE")
        state["codeowners"] = {HOME: {".github/CODEOWNERS": "* @maintainer"}}
        process = self.run_dag(state, "--from-github", "--trust-codeowners")
        result = self.out(process)
        self.assertEqual(process.returncode, 0, result)
        self.assertIn(f"{HOME}#1", self.ids(result))
        self.assertFalse(self.node(result, f"{HOME}#1")["untrusted"])
        self.assertEqual(field(result, "source", "trust", "codeowners"), {HOME: ["maintainer"]})
        self.assertEqual(field(result, "source", "trust", "codeowners_teams_not_expanded"), {})
