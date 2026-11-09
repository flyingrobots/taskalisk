"""Check process-group cleanup and limits against real POSIX failure paths."""

from __future__ import annotations

import fcntl
import os
import signal
import sys
import tempfile
import unittest
from contextlib import suppress
from pathlib import Path

from skills.taskalisk.scripts.taskalisk_core.process import run_cmd_checked
from skills.taskalisk.scripts.taskalisk_core.process_limits import CommandLimits

TREE = """
import fcntl, os, signal, sys
from pathlib import Path
read_fd, write_fd = os.pipe()
parent = os.getpid()
child = os.fork()
if child == 0:
    lock = open(sys.argv[1], 'w')
    fcntl.flock(lock, fcntl.LOCK_EX)
    Path(sys.argv[2]).write_text(f'{parent} {os.getpid()}')
    os.write(write_fd, b'ready')
    signal.alarm(5)
    signal.pause()
else:
    os.read(read_fd, 5)
    signal.alarm(5)
    signal.pause()
"""


def lock_available(path: Path) -> bool:
    """Observe whether the descendant still owns its exclusive kernel lock."""
    with path.open("a", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True


def cleanup_witness(path: Path) -> None:
    """Clean a surviving fault-injected descendant only while its group matches."""
    parent, child = map(int, path.read_text(encoding="utf-8").split())
    with suppress(ProcessLookupError):
        if os.getpgid(child) == parent:
            os.kill(child, signal.SIGKILL)


class ProcessLifetime(unittest.TestCase):
    """Process admission, timeout and cancellation retain ownership."""

    def test_lock_oracle_distinguishes_a_live_owner_from_release(self) -> None:
        """The cleanup oracle must reject a held lock, then admit its release."""
        with tempfile.TemporaryDirectory(prefix="taskalisk-lock-") as directory:
            path = Path(directory) / "lock"
            with path.open("a", encoding="utf-8") as owner:
                fcntl.flock(owner, fcntl.LOCK_EX)
                with self.subTest(check="held"):
                    self.assertFalse(lock_available(path))
            with self.subTest(check="released"):
                self.assertTrue(lock_available(path))

    def test_invalid_limits_cannot_disable_enforcement(self) -> None:
        """Reject nonfinite/nonpositive time and nonintegral/nonpositive bytes."""
        for seconds in (0.0, -1.0, float("inf"), float("nan")):
            with (
                self.subTest(seconds=seconds),
                self.assertRaisesRegex(ValueError, "finite and positive"),
            ):
                CommandLimits(timeout_seconds=seconds)
        for maximum in (0, -1, True):
            with (
                self.subTest(maximum=maximum),
                self.assertRaisesRegex(ValueError, "positive integer"),
            ):
                CommandLimits(max_bytes=maximum)

    def test_deadline_stops_a_descendant_holding_an_external_lock(self) -> None:
        """Leader termination alone cannot release a separate child's lock."""
        with tempfile.TemporaryDirectory(prefix="taskalisk-tree-") as directory:
            path = Path(directory) / "lock"
            witness = Path(directory) / "ready"
            result = run_cmd_checked(
                [sys.executable, "-c", TREE, str(path), str(witness)],
                limits=CommandLimits(timeout_seconds=1),
            )
            try:
                with self.subTest(check="ready"):
                    self.assertTrue(witness.is_file(), result)
                with self.subTest(check="status"):
                    self.assertEqual(result[:2], (False, ""))
                with self.subTest(check="cleanup"):
                    self.assertTrue(lock_available(path), "descendant still owns its kernel lock")
            finally:
                if witness.is_file():
                    cleanup_witness(witness)

    def test_closed_pipes_do_not_remove_the_exit_deadline(self) -> None:
        """A leader may keep running after EOF on every captured stream."""
        source = "import os, signal; os.close(0); os.close(1); os.close(2); signal.alarm(2); signal.pause()"
        ok, output, error = run_cmd_checked(
            [sys.executable, "-c", source], limits=CommandLimits(timeout_seconds=0.25)
        )
        with self.subTest(check="status"):
            self.assertEqual((ok, output), (False, ""))
        with self.subTest(check="diagnostic"):
            self.assertIn("deadline exceeded", error)

    def test_unread_stdin_does_not_block_deadline_enforcement(self) -> None:
        """A pipe-sized input cannot block the supervisor's write operation."""
        source = "import signal; signal.alarm(2); signal.pause()"
        ok, output, error = run_cmd_checked(
            [sys.executable, "-c", source],
            input_text="a" * 200_000,
            limits=CommandLimits(timeout_seconds=0.25),
        )
        with self.subTest(check="status"):
            self.assertEqual((ok, output), (False, ""))
        with self.subTest(check="diagnostic"):
            self.assertIn("deadline exceeded", error)

    def test_early_input_close_can_still_return_a_command_error(self) -> None:
        """Broken stdin does not obscure the program's own refusal diagnostic."""
        source = "import os; os.close(0); os.write(2, b'refused'); raise SystemExit(4)"
        result = run_cmd_checked([sys.executable, "-c", source], input_text="a" * 200_000)
        self.assertEqual(result, (False, "", "refused"))

    def test_character_bound_precedes_utf8_encoding_and_spawn(self) -> None:
        """Even single-byte input is admitted before a child can start."""
        result = run_cmd_checked(
            [sys.executable, "-c", "raise SystemExit(0)"],
            input_text="a" * 4097,
            limits=CommandLimits(max_bytes=4096),
        )
        self.assertEqual(result, (False, "", "CommandLimitError: command input exceeds 4096 bytes"))

    def test_exact_output_limit_is_allowed(self) -> None:
        """The ceiling is inclusive; refusal is not an off-by-one policy."""
        result = run_cmd_checked(
            [sys.executable, "-c", "import os; os.write(1, b'a' * 4096)"],
            limits=CommandLimits(max_bytes=4096),
        )
        self.assertEqual(result, (True, "a" * 4096, ""))
