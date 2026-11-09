"""Observe an exclusively owned child exiting without releasing its identity."""

from __future__ import annotations

import errno
import os
import select
import sys
import time
from contextlib import closing


def wait_unreaped(pid: int, timeout_seconds: float) -> bool:
    """Wait at most the deadline for an owned, never-reaped child to exit.

    The caller must exclusively own this child and must not install a competing
    reaper. On older macOS Python, kqueue supplies the non-reaping observation;
    ESRCH there means this retained child has already exited. Linux has waitid.
    """
    if sys.platform == "darwin":
        with closing(select.kqueue()) as queue:
            event = select.kevent(
                pid,
                filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                fflags=select.KQ_NOTE_EXIT,
            )
            observed = queue.control([event], 1, timeout_seconds)
            if not observed:
                return False
            if observed[0].flags & select.KQ_EV_ERROR and observed[0].data != errno.ESRCH:
                raise OSError(observed[0].data, "cannot observe owned child exit")
            return True
    else:
        deadline = time.monotonic() + timeout_seconds
        while os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.01, remaining))
        return True
