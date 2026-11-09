"""Own bounded pipe I/O and termination for one POSIX command process group."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from contextlib import ExitStack, suppress
from typing import IO

from .process_exit import wait_unreaped
from .process_limits import CommandLimits


class CommandLimitError(Exception):
    """The command exceeded its finite input, output or elapsed-time budget."""


def encode_input(text: str, maximum: int) -> bytes:
    """Check characters before allocating at most four bytes per character."""
    if len(text) > maximum:
        message = f"command input exceeds {maximum} bytes"
        raise CommandLimitError(message)
    payload = text.encode("utf-8")
    if len(payload) > maximum:
        message = f"command input exceeds {maximum} bytes"
        raise CommandLimitError(message)
    return payload


def stop_group(child: subprocess.Popen[bytes]) -> None:
    """Stop the owned group and reap its leader, including on cancellation.

    Descendants that stay in the group receive SIGKILL. Orphan reaping belongs
    to the OS; a detached process or remote effect is outside this boundary.
    Cleanup failure propagates rather than falsely acknowledging termination.
    """
    try:
        try:
            # The group may already have exited; only that absence is harmless.
            with suppress(ProcessLookupError):
                os.killpg(child.pid, signal.SIGKILL)
        except PermissionError:
            # Darwin can report EPERM for a group containing only its zombie
            # leader. Reap it, then probe with signal 0: never signal a released
            # identity. A surviving/inaccessible group remains a cleanup error.
            child.wait(timeout=5)
            if group_exists(child.pid):
                raise
            return
        child.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        message = "command cleanup failed: group termination or leader reaping failed"
        raise RuntimeError(message) from error


def group_exists(group_id: int) -> bool:
    """Observe group existence without delivering a signal to any member."""
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class PipeCapture:
    """Pump owned pipes without blocking on either output or an unread input."""

    def __init__(self, limits: CommandLimits, payload: bytes) -> None:
        """Retain a bounded input and initialize one command's accounting."""
        self.limits = limits
        self.payload = payload
        self.offset = 0
        self.total = 0
        self.deadline = time.monotonic() + limits.timeout_seconds
        self.input_fd = -1
        self.buffers: dict[int, bytearray] = {}
        self.streams: dict[int, IO[bytes]] = {}

    def remaining(self) -> float:
        """Return the remaining deadline or refuse another blocking operation."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            message = f"command deadline exceeded ({self.limits.timeout_seconds:g} seconds)"
            raise CommandLimitError(message)
        return remaining

    def register(
        self, events: selectors.BaseSelector, stream: IO[bytes], *, writing: bool = False
    ) -> None:
        """Register a nonblocking pipe owned by the caller's ExitStack."""
        descriptor = stream.fileno()
        self.streams[descriptor] = stream
        os.set_blocking(descriptor, False)
        if writing:
            self.input_fd = descriptor
            if not self.payload:
                stream.close()
                return
            events.register(stream, selectors.EVENT_WRITE)
        else:
            self.buffers[descriptor] = bytearray()
            events.register(stream, selectors.EVENT_READ)

    def transfer(self, events: selectors.BaseSelector, descriptor: int) -> None:
        """Move at most 64 KiB and reject output at the first excess byte."""
        if descriptor == self.input_fd:
            self.write_input(events, descriptor)
            return
        chunk = os.read(descriptor, min(65536, self.limits.max_bytes - self.total + 1))
        if not chunk:
            events.unregister(descriptor)
            return
        self.total += len(chunk)
        if self.total > self.limits.max_bytes:
            message = f"command output exceeds {self.limits.max_bytes} bytes"
            raise CommandLimitError(message)
        self.buffers[descriptor].extend(chunk)

    def write_input(self, events: selectors.BaseSelector, descriptor: int) -> None:
        """Handle partial writes and early stdin closure without retrying a command."""
        try:
            self.offset += os.write(descriptor, self.payload[self.offset : self.offset + 65536])
        except BrokenPipeError:
            self.offset = len(self.payload)
        if self.offset == len(self.payload):
            events.unregister(descriptor)
            self.streams[descriptor].close()

    def wait_for_exit(self, pid: int) -> None:
        """Observe exit without reaping, retaining the group's identity anchor."""
        if not wait_unreaped(pid, self.remaining()):
            message = "command deadline exceeded while waiting for exit"
            raise CommandLimitError(message)

    def collect(self, child: subprocess.Popen[bytes], stack: ExitStack) -> tuple[str, str]:
        """Drain both output streams and bound the subsequent leader exit wait."""
        if child.stdin is None or child.stdout is None or child.stderr is None:
            message = "command pipe setup is incomplete"
            raise RuntimeError(message)
        with selectors.DefaultSelector() as events:
            for stream in (child.stdin, child.stdout, child.stderr):
                stack.enter_context(stream)
            self.register(events, child.stdin, writing=True)
            self.register(events, child.stdout)
            self.register(events, child.stderr)
            while events.get_map():
                for key, _ in events.select(self.remaining()):
                    self.transfer(events, key.fd)
            self.wait_for_exit(child.pid)
        return (
            self.buffers[child.stdout.fileno()].decode("utf-8").strip(),
            self.buffers[child.stderr.fileno()].decode("utf-8").strip(),
        )


def run_limited(
    cmd: list[str], cwd: str | None, limits: CommandLimits, input_text: str
) -> tuple[bool, str, str]:
    """Run argv on POSIX; bound retained bytes and stop the group on every exit.

    The caller supplies trusted executables and owns any remote-effect decision.
    No retry occurs. The current environment intentionally carries gh credentials
    and PATH. Unsupported hosts refuse before starting an unbounded child.
    """
    if os.name != "posix":
        message = "bounded command execution requires a POSIX host"
        raise OSError(message)
    capture = PipeCapture(limits, encode_input(input_text, limits.max_bytes))
    # policy-exception: PY-COMMAND-ARGV -- Internal callers supply fixed executable argv; no shell.
    child = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=dict(os.environ),
    )
    with ExitStack() as stack:
        try:
            output, error = capture.collect(child, stack)
        finally:
            stop_group(child)
        return child.returncode == 0, output, error
