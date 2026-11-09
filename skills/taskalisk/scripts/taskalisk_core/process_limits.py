"""Declare the per-command deadline and input/output budgets."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class CommandLimits:
    """Bound one command; input and combined output each have a byte ceiling."""

    timeout_seconds: float = 60.0
    max_bytes: int = 32 * 1024 * 1024

    def __post_init__(self) -> None:
        """Reject disabled or unbounded limits on every normal construction."""
        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            message = "command deadline must be finite and positive"
            raise ValueError(message)
        if type(self.max_bytes) is not int or self.max_bytes <= 0:
            message = "command byte limit must be a positive integer"
            raise ValueError(message)
