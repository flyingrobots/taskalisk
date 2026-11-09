"""Observe kernel child ownership across pipe capture and process-group cleanup."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from contextlib import ExitStack

from skills.taskalisk.scripts.taskalisk_core.process_capture import PipeCapture, stop_group
from skills.taskalisk.scripts.taskalisk_core.process_limits import CommandLimits


class ProcessOwnership(unittest.TestCase):
    """The leader's identity stays reserved until group termination finishes."""

    def test_capture_retains_unreaped_leader_for_group_shutdown(self) -> None:
        """An independently observed waitable child anchors the process-group ID."""
        child = subprocess.Popen(
            [sys.executable, "-c", "print('complete')"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        reaped = False
        with ExitStack() as stack:
            try:
                result = PipeCapture(CommandLimits(timeout_seconds=5), b"").collect(child, stack)
                with self.subTest(check="output"):
                    self.assertEqual(result, ("complete", ""))
                with self.subTest(check="ownership"):
                    try:
                        pid, status = os.waitpid(child.pid, os.WNOHANG)
                    except ChildProcessError:
                        self.fail("leader reaped before process-group shutdown")
                    reaped = pid == child.pid
                    if reaped:
                        child.returncode = os.waitstatus_to_exitcode(status)
                    self.assertEqual(pid, child.pid, "capture returned before leader exit")
            finally:
                # This probe consumes the leaf child's wait status. Never signal
                # the numeric group after releasing that identity.
                if not reaped:
                    stop_group(child)
