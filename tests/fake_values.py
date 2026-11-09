"""Check decoded fixture shapes without importing production admission logic."""

from __future__ import annotations

from typing import cast


def fields(value: object) -> dict[str, object]:
    """Copy a checked object while leaving every member value unknown."""
    message = "fixture object with string keys required"
    if not isinstance(value, dict):
        raise TypeError(message)
    # isinstance proves only the dictionary container, not its key/value types.
    entries = cast("dict[object, object]", value)
    result: dict[str, object] = {}
    for key, item in entries.items():
        if not isinstance(key, str):
            raise TypeError(message)
        result[key] = item
    return result


def items(value: object) -> list[object]:
    """Require an array without claiming a schema for its members."""
    if not isinstance(value, list):
        message = "fixture array required"
        raise TypeError(message)
    # The checked list container contains unknown values; no element type is admitted.
    return cast("list[object]", value)


def text(value: object) -> str:
    """Require text without coercing falsey or otherwise printable values."""
    if not isinstance(value, str):
        message = "fixture text required"
        raise TypeError(message)
    return value


def integer(value: object) -> int:
    """Require an actual integer, excluding bool and numeric coercion."""
    if type(value) is not int:
        message = "fixture integer required"
        raise TypeError(message)
    return value
