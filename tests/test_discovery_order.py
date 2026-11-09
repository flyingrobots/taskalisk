"""Preserve discovery order where late references and failed trust lookups matter."""

from cli_fixture import HOME, STRANGER, Harness, fm, issue
from fake_values import field, records
from fixture_models import FakeState


def two_seeds() -> FakeState:
    """Build two independent home seeds in their deterministic visit order."""
    return {
        "home": HOME,
        "blocked_by": {},
        "issues": {
            f"{HOME}#1": issue(101, "First", fm(f"{HOME}#1")),
            f"{HOME}#2": issue(102, "Second", fm(f"{HOME}#2")),
        },
    }


class DiscoveryOrder(Harness):
    """A phase boundary must retain late references and stop after lookup failure."""

    def test_later_trusted_reference_retains_an_earlier_untrusted_seed(self) -> None:
        """The exclusion report and opaque blocker both acquire the later trusted reference."""
        state = two_seeds()
        state["issues"][f"{HOME}#1"] = issue(
            101,
            "UNTRUSTED TITLE MUST NOT APPEAR",
            fm(
                f"{HOME}#1",
                blocked_by=["mallory/hidden#99"],
                extra=".holds: [host/all/]\n.meters: [gpu*2]",
            ),
            options={"author": STRANGER, "association": "NONE"},
        )
        state["issues"][f"{HOME}#2"]["body"] = fm(f"{HOME}#2", blocked_by=[f"{HOME}#1"])
        process = self.run_dag(state, "--from-github")
        result = self.out(process)
        self.assertEqual(process.returncode, 0, result)
        self.assertEqual(self.ids(result), [f"{HOME}#1", f"{HOME}#2"])
        self.assertEqual(
            records(field(result, "source", "untrusted_issues"))[0]["referenced_by"], [f"{HOME}#2"]
        )
        blocker = self.node(result, f"{HOME}#1")
        self.assertEqual(
            (blocker["title"], blocker["holds"], blocker["meters"], blocker["open_parents"]),
            ("(untrusted issue)", [], [], []),
        )
        self.assertEqual(self.node(result, f"{HOME}#2")["open_parents"], [f"{HOME}#1"])
        self.assertNotIn("UNTRUSTED TITLE MUST NOT APPEAR", process.stdout)
        self.assertFalse(any("mallory/hidden" in " ".join(call) for call in self.calls()))
        self.assertFalse(
            any(call[:2] == ["api", "graphql"] and "number=1" in call for call in self.calls())
        )

    def test_out_of_scope_reference_reports_every_source_without_a_fetch(self) -> None:
        """Both referencing seeds retain the same scope violation before the target is visited."""
        state = two_seeds()
        for number in (1, 2):
            state["issues"][f"{HOME}#{number}"]["body"] = fm(
                f"{HOME}#{number}", blocked_by=["mallory/hidden#99"]
            )
        process = self.run_dag(state, "--from-github")
        result = self.out(process)
        self.assertEqual(process.returncode, 1, result)
        message = "reference mallory/hidden#99 is outside the trusted repositories; add --trust-owner mallory or --trust-repo mallory/hidden"
        self.assertEqual(
            field(result, "frontmatter", "violations"),
            {f"{HOME}#1": [message], f"{HOME}#2": [message]},
        )
        self.assertFalse(any("mallory/hidden" in " ".join(call) for call in self.calls()))

    def test_history_lookup_failure_stops_before_the_next_seed(self) -> None:
        """A failed first history lookup cannot produce a partial plan or query later seeds."""
        state = two_seeds()
        state["fail_graphql_for"] = [f"{HOME}#1"]
        process = self.run_dag(state, "--from-github")
        result = self.out(process)
        self.assertEqual(process.returncode, 2, result)
        self.assertFalse(result["ok"])
        self.assertNotIn("waves", result)
        calls = [call for call in self.calls() if call[:2] == ["api", "graphql"]]
        self.assertEqual(len(calls), 1)
        self.assertIn("number=1", calls[0])
