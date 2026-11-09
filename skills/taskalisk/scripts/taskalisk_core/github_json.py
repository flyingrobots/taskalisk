"""Decode bounded GitHub JSON without ambiguous keys, numbers or partial pages."""

from __future__ import annotations

import json
from math import isfinite
from typing import cast

from .github_json_limits import JsonLimits

JSON_WHITESPACE = " \t\r\n"


def _check_text(raw: str, limits: JsonLimits) -> None:
    """Refuse missing or oversized text before allocating decoded values."""
    if len(raw) > limits.max_bytes or len(raw.encode("utf-8")) > limits.max_bytes:
        message = f"response exceeds {limits.max_bytes} UTF-8 bytes"
        raise ValueError(message)
    if not raw.strip(JSON_WHITESPACE):
        message = "empty response"
        raise ValueError(message)


def _check_envelope(raw: str, limits: JsonLimits) -> None:
    """Bound bytes before parsing, and structural work without counting strings."""
    _check_text(raw, limits)
    depth = tokens = 0
    quoted = escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "{}[],:":
            tokens += 1
            depth += int(char in "{[") - int(char in "}]")
            if depth > limits.max_depth:
                message = f"container depth exceeds {limits.max_depth}"
                raise ValueError(message)
            if tokens > limits.max_tokens:
                message = f"structural tokens exceed {limits.max_tokens}"
                raise ValueError(message)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject a duplicate before it can overwrite a prior member's meaning."""
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            message = "duplicate object key"
            raise ValueError(message)
        fields[key] = value
    return fields


def _numeric_token(token: str) -> str:
    """Bound numeric conversion before calling int or float."""
    if len(token) > 128:
        message = "numeric token exceeds 128 characters"
        raise ValueError(message)
    return token


def _integer(token: str) -> int:
    """Decode a bounded decimal integer without changing the interpreter limit."""
    return int(_numeric_token(token))


def _floating(token: str) -> float:
    """Reject both nonstandard constants and ordinary exponent overflow."""
    value = float(_numeric_token(token))
    if not isfinite(value):
        message = "non-finite number"
        raise ValueError(message)
    return value


def _decoder() -> json.JSONDecoder:
    """Use the same unambiguous grammar for a single document and every page."""
    return json.JSONDecoder(
        object_pairs_hook=_unique_object,
        parse_int=_integer,
        parse_float=_floating,
        parse_constant=_floating,
    )


def _check_unicode(value: object) -> None:
    """Reject escaped lone surrogates after decoding, including object keys."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeError as error:
                message = "invalid Unicode scalar"
                raise ValueError(message) from error
        elif isinstance(item, dict):
            # Only the runtime-checked container is claimed; members remain object.
            fields = cast("dict[object, object]", item)
            pending.extend(fields)
            pending.extend(fields.values())
        elif isinstance(item, list):
            # Only the runtime-checked list is claimed, without admitting element types.
            pending.extend(cast("list[object]", item))


def object_fields(value: object) -> dict[str, object] | None:
    """Copy a mapping only after checking its container and all key types."""
    if not isinstance(value, dict):
        return None
    # isinstance establishes the container; object/object asserts no field type.
    entries = cast("dict[object, object]", value)
    fields: dict[str, object] = {}
    for key, item in entries.items():
        if not isinstance(key, str):
            return None
        fields[key] = item
    return fields


def _object_rows(value: object) -> list[dict[str, object]]:
    """Validate every row before admitting any part of the array."""
    message = "Expected a JSON array of objects"
    if not isinstance(value, list):
        raise TypeError(message)
    # Only the checked list container is claimed; each element is still unknown.
    entries = cast("list[object]", value)
    rows: list[dict[str, object]] = []
    for entry in entries:
        fields = object_fields(entry)
        if fields is None:
            raise TypeError(message)
        rows.append(fields)
    return rows


def parse_json(
    raw: str, source: str, errors: list[dict[str, str]], *, limits: JsonLimits | None = None
) -> object:
    """Decode one bounded document, recording failure separately from JSON null."""
    try:
        _check_envelope(raw, limits or JsonLimits())
        decoded: object = _decoder().decode(raw)
        _check_unicode(decoded)
    except ValueError as error:
        errors.append({"source": source, "error": f"Unparseable JSON output: {error}"})
        return None
    return decoded


def parse_json_list(
    raw: str, source: str, errors: list[dict[str, str]], *, limits: JsonLimits | None = None
) -> list[dict[str, object]]:
    """Decode exactly one object array; failure never admits a partial list."""
    before = len(errors)
    decoded = parse_json(raw, source, errors, limits=limits)
    if len(errors) != before:
        return []
    try:
        return _object_rows(decoded)
    except TypeError as error:
        errors.append({"source": source, "error": str(error)})
        return []


def parse_paginated_arrays(
    raw: str, source: str, errors: list[dict[str, str]], *, limits: JsonLimits | None = None
) -> list[dict[str, object]]:
    """Read concatenated array documents from gh api --paginate, all or nothing."""
    rows: list[dict[str, object]] = []
    try:
        _check_envelope(raw, limits or JsonLimits())
        text = raw.strip(JSON_WHITESPACE)
        decoder = _decoder()
        index = 0
        while index < len(text):
            page: object
            page, index = decoder.raw_decode(text, index)
            _check_unicode(page)
            rows.extend(_object_rows(page))
            while index < len(text) and text[index] in JSON_WHITESPACE:
                index += 1
    except (TypeError, ValueError) as error:
        errors.append({"source": source, "error": f"Unparseable JSON page: {error}"})
        return []
    return rows
