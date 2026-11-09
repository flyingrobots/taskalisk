"""Check local specification primitives without scalar coercion."""

from __future__ import annotations

from math import isfinite
from typing import cast

from .github_json import object_fields


def fields(value: object, name: str) -> dict[str, object]:
    """Admit an object only after checking its container and every key."""
    result = object_fields(value)
    if result is None:
        message = f"{name} must be an object"
        raise TypeError(message)
    return result


def array(value: object, name: str) -> list[object]:
    """Admit a list container while leaving each member untrusted."""
    if not isinstance(value, list):
        message = f"{name} must be an array"
        raise TypeError(message)
    return cast("list[object]", value)


def text(value: object, name: str) -> str:
    """Require text without interpreting numbers or Booleans as names."""
    if not isinstance(value, str):
        message = f"{name} must be text"
        raise TypeError(message)
    return value


def identifier(value: object, name: str) -> str:
    """Require a nonempty name while preserving its original spelling."""
    result = text(value, name)
    if not result.strip():
        message = f"{name} must not be empty"
        raise ValueError(message)
    return result


def nullable_text(value: object, name: str) -> str | None:
    """Preserve explicit or default null text fields."""
    return None if value is None else text(value, name)


def boolean(value: object, name: str) -> bool:
    """Require an actual Boolean rather than Python truthiness."""
    if not isinstance(value, bool):
        message = f"{name} must be a Boolean"
        raise TypeError(message)
    return value


def positive_integer(value: object, name: str) -> int:
    """Exclude Boolean and numeric text from positive counts."""
    if type(value) is not int or value <= 0:
        message = f"{name} must be a positive integer"
        raise ValueError(message)
    return value


def confidence(value: object) -> float:
    """Admit only finite numeric confidence in the closed unit interval."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        message = "confidence must be a number"
        raise TypeError(message)
    if not 0 <= value <= 1 or not isfinite(value):
        message = "confidence must be between 0 and 1"
        raise ValueError(message)
    return float(value)


def identifiers(value: object, name: str) -> list[str]:
    """Check the complete list before returning any admitted names."""
    return [identifier(item, f"{name} entry") for item in array(value, name)]
