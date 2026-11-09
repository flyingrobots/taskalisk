"""Check Resources behavior through the public CLI."""

from cli_fixture import HOME, Harness, fm, issue
from fake_values import records, text
from fixture_models import FakeState


class Resources(Harness):
    def frontier_state(self, extra_a: str, extra_b: str) -> FakeState:
        return {
            "home": HOME,
            "blocked_by": {},
            "issues": {
                f"{HOME}#1": issue(101, "A", fm(f"{HOME}#1", extra=extra_a)),
                f"{HOME}#2": issue(102, "B", fm(f"{HOME}#2", extra=extra_b)),
            },
        }

    def batch(self, state: FakeState, *args: str) -> list[str]:
        return [
            text(b["id"])
            for b in records(
                self.out(self.run_dag(state, "--from-github", *args))[
                    "conflict_free_frontier_batch"
                ]
            )
        ]

    def test_no_resources_means_full_parallelism(self):
        self.assertEqual(
            sorted(self.batch(self.frontier_state("", ""))), [f"{HOME}#1", f"{HOME}#2"]
        )

    def test_overlapping_holds_conflict(self):
        self.assertEqual(
            len(
                self.batch(
                    self.frontier_state(".holds: [host/docker/w/]", ".holds: [host/docker/w/cache]")
                )
            ),
            1,
        )

    def test_unknown_semaphore_capacity_is_exclusive(self):
        state = self.frontier_state(".meters: [gpu]", ".meters: [gpu]")
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(len(records(r["conflict_free_frontier_batch"])), 1)
        self.assertEqual(r["semaphores_with_unknown_capacity_treated_as_1"], ["gpu"])

    def test_declared_semaphore_capacity_allows_parallel_slots(self):
        state = self.frontier_state(".meters: [gpu]", ".meters: [gpu]")
        self.assertEqual(len(self.batch(state, "--sem-capacity", "gpu=2")), 2)

    def test_multi_slot_meter_respects_capacity(self):
        state = self.frontier_state(".meters: [gpu*2]", ".meters: [gpu]")
        self.assertEqual(len(self.batch(state, "--sem-capacity", "gpu=2")), 1)
