"""Run external commands and decode their JSON envelopes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .process_capture import CommandLimitError, run_limited
from .process_limits import CommandLimits


def sanitize_home(text: str) -> str:
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


def parse_json(raw: str, source: str, errors: list[dict[str, str]]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        errors.append({"source": source, "error": f"Unparseable JSON output: {exc}"})
        return None


def parse_json_list(raw: str, source: str, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    parsed = parse_json(raw, source, errors)
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        errors.append({"source": source, "error": "Expected a JSON array"})
        return []
    return parsed


def parse_paginated_arrays(
    raw: str, source: str, errors: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """`gh api --paginate` concatenates arrays as separate JSON documents; split them."""
    items: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    idx = 0
    text = raw.strip()
    while idx < len(text):
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError as exc:
            errors.append({"source": source, "error": f"Unparseable JSON: {exc}"})
            return []
        if not isinstance(obj, list):
            errors.append({"source": source, "error": "Expected a JSON array page"})
            return []
        items.extend(obj)
        idx = end
        while idx < len(text) and text[idx].isspace():
            idx += 1
    return items
