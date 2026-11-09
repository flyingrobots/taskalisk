"""Read one regular local spec with bounded bytes and unambiguous JSON."""

from __future__ import annotations

import os
import stat

from .github_json import parse_json
from .github_json_limits import JsonLimits
from .graph_values import DagSpec
from .spec_values import parse_spec


def read_spec(path: str, *, limits: JsonLimits | None = None) -> DagSpec:
    """Bound accepted bytes; this is neither an atomic snapshot nor an I/O deadline."""
    limits = limits or JsonLimits()
    # Nonblocking open lets us reject a FIFO before waiting for an absent writer.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            message = "DAG spec must be a regular file"
            raise ValueError(message)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1  # fdopen now owns closing, including read failures.
            raw = stream.read(limits.max_bytes + 1)
    finally:
        if descriptor != -1:
            os.close(descriptor)
    if len(raw) > limits.max_bytes:
        message = f"DAG spec exceeds {limits.max_bytes} bytes"
        raise ValueError(message)
    errors: list[dict[str, str]] = []
    value = parse_json(raw.decode("utf-8"), "DAG spec", errors, limits=limits)
    if errors:
        raise ValueError(errors[0]["error"])
    return parse_spec(value)
