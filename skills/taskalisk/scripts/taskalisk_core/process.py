"""Run bounded external commands and sanitize their diagnostic envelopes."""

from __future__ import annotations

from pathlib import Path

from .process_capture import CommandLimitError, run_limited
from .process_limits import CommandLimits


def sanitize_home(text: str) -> str:
    """Replace the current home path in operator-facing diagnostics."""
    home = str(Path.home())
    if home and home != "/":
        return text.replace(home, "~")
    return text


def run_cmd_checked(
    cmd: list[str],
    cwd: str | None = None,
    *,
    limits: CommandLimits | None = None,
    input_text: str | None = None,
) -> tuple[bool, str, str]:
    """Run trusted argv within limits, returning status, stdout and safe stderr.

    A failed or cancelled local command does not establish a remote write's
    outcome. No automatic retry occurs. Cancellation and cleanup failures
    propagate; ordinary spawn, limit and encoding failures become diagnostics.
    """
    try:
        ok, output, error = run_limited(cmd, cwd, limits or CommandLimits(), input_text or "")
    except (OSError, CommandLimitError) as exc:
        return False, "", sanitize_home(f"{type(exc).__name__}: {exc}")
    except UnicodeError:
        return False, "", "command protocol contains invalid UTF-8"
    return ok, output, sanitize_home(error)
