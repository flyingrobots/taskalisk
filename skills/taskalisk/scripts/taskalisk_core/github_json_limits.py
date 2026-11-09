"""Declare bounded JSON decoding work at the GitHub response boundary."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JsonLimits:
    """Cap UTF-8 bytes, container depth and punctuation outside strings."""

    max_bytes: int = 32 * 1024 * 1024
    max_depth: int = 32
    max_tokens: int = 100_000

    def __post_init__(self) -> None:
        """Permit narrower budgets, never disabled or expanded global ceilings."""
        for name, value, ceiling in (
            ("bytes", self.max_bytes, 32 * 1024 * 1024),
            ("depth", self.max_depth, 32),
            ("tokens", self.max_tokens, 100_000),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                message = f"JSON {name} limit must be a positive integer at most {ceiling}"
                raise ValueError(message)
