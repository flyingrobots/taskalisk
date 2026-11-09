"""Run external commands and decode their JSON envelopes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def sanitize_home(text: str) -> str:
    home = str(Path.home())
    if home and home != "/":
        return text.replace(home, "~")
    return text


def run_cmd_checked(cmd: list[str], cwd: str | None = None) -> tuple[bool, str, str]:
    """Run a command; never raise. Returns (ok, stdout, sanitized stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        return False, "", sanitize_home(f"{type(exc).__name__}: {exc}")
    return (
        proc.returncode == 0,
        proc.stdout.strip(),
        sanitize_home(proc.stderr.strip()),
    )


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
