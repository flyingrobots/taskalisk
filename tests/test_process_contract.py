"""Exercise command limits and process ownership using real local children."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from skills.taskalisk.scripts.taskalisk_core.process import run_cmd_checked
from skills.taskalisk.scripts.taskalisk_core.process_limits import CommandLimits


def command(source: str) -> list[str]:
    """Use the prepared interpreter, with no shell or GitHub interaction."""
    return [sys.executable, "-c", source]


class ProcessContract(unittest.TestCase):
    """A failed command never produces successful protocol output."""

    def test_success_preserves_stdout_and_separate_diagnostics(self) -> None:
        """Normal bounded commands retain the existing stripped text contract."""
        result = run_cmd_checked(
            command("import sys; print(' value '); print(' note ', file=sys.stderr)")
        )
        self.assertEqual(result, (True, "value", "note"))

    def test_nonzero_exit_preserves_diagnostics_and_status(self) -> None:
        """An executable failure is distinct from successful empty output."""
        result = run_cmd_checked(
            command("import sys; print('denied', file=sys.stderr); sys.exit(7)")
        )
        self.assertEqual(result, (False, "", "denied"))

    def test_deadline_refuses_a_child_that_would_eventually_succeed(self) -> None:
        """A finite alarm bounds the RED witness even before runner enforcement."""
        source = "import signal; signal.signal(signal.SIGALRM, lambda *_: exit(0)); signal.alarm(2); signal.pause()"
        ok, output, error = run_cmd_checked(
            command(source), limits=CommandLimits(timeout_seconds=0.25)
        )
        with self.subTest(check="status"):
            self.assertEqual((ok, output), (False, ""))
        with self.subTest(check="diagnostic"):
            self.assertIn("deadline exceeded", error)

    def test_output_limit_counts_both_streams_and_discards_partial_protocol(self) -> None:
        """Neither stream alone exceeds the cap; their combined bytes do."""
        source = "import os; os.write(1, b'a' * 3000); os.write(2, b'b' * 3000)"
        ok, output, error = run_cmd_checked(command(source), limits=CommandLimits(max_bytes=4096))
        with self.subTest(check="status"):
            self.assertEqual((ok, output), (False, ""))
        with self.subTest(check="diagnostic"):
            self.assertIn("output exceeds 4096 bytes", error)

    def test_input_round_trip_handles_pipe_sized_payload(self) -> None:
        """Partial writes cannot truncate a valid input document."""
        payload = "é" * 100_000
        result = run_cmd_checked(
            command("import sys; sys.stdout.write(sys.stdin.read())"), input_text=payload
        )
        self.assertEqual(result, (True, payload, ""))

    def test_oversized_input_is_refused_before_starting_the_command(self) -> None:
        """The filesystem witness detects execution despite admission refusal."""
        with tempfile.TemporaryDirectory(prefix="taskalisk-command-") as directory:
            witness = Path(directory) / "executed"
            source = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran'); sys.stdin.read()"
            invocation = [*command(source), str(witness)]
            ok, output, error = run_cmd_checked(
                invocation, input_text="é" * 3000, limits=CommandLimits(max_bytes=4096)
            )
            with self.subTest(check="status"):
                self.assertEqual((ok, output), (False, ""))
            with self.subTest(check="diagnostic"):
                self.assertIn("input exceeds 4096 bytes", error)
            with self.subTest(check="effect"):
                self.assertFalse(witness.exists())

    def test_invalid_utf8_is_a_failed_protocol_read(self) -> None:
        """A malformed byte stream cannot silently become a replacement character."""
        ok, output, error = run_cmd_checked(command("import os; os.write(1, b'\\xff')"))
        with self.subTest(check="status"):
            self.assertEqual((ok, output), (False, ""))
        with self.subTest(check="diagnostic"):
            self.assertIn("invalid UTF-8", error)

    def test_spawn_errors_are_sanitized_failures(self) -> None:
        """Missing commands keep the failure envelope and redact the home path."""
        missing = str(Path.home() / ".taskalisk-missing-command")
        ok, output, error = run_cmd_checked([missing])
        with self.subTest(check="status"):
            self.assertEqual((ok, output), (False, ""))
        with self.subTest(check="diagnostic"):
            self.assertIn("FileNotFoundError", error)
        with self.subTest(check="redaction"):
            self.assertNotIn(str(Path.home()), error)
