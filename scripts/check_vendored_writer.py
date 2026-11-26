#!/usr/bin/env python3
"""Prove that the vendored Parley writer is the file flyingrobots/parley published at the pinned commit.

`skills/taskalisk/scripts/parley_emit.pin.json` names the commit. This script fetches
`packages/parley-emit-py/parley_emit.py` at that commit and requires its SHA-256 and size to equal
the pin's and the local copy's. The offline test `Vendored.test_copy_matches_its_pin` proves only
that the copy has not drifted from its pin; this check proves provenance, and needs the network.

Usage: python3 scripts/check_vendored_writer.py   (exit 0: upstream matches; 1: it does not, or the
fetch failed; a failed fetch is never a pass)
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "taskalisk" / "scripts"
UPSTREAM = "https://raw.githubusercontent.com/flyingrobots/parley/{commit}/packages/parley-emit-py/parley_emit.py"
TIMEOUT_SECONDS = 30


def upstream_url(pin):
    return UPSTREAM.format(commit=pin["parley_commit"])


def fetch(url, limit=None):
    """The bytes at url; with a limit, at most one byte past it, enough to see a longer file."""
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        return response.read(limit + 1) if limit is not None else response.read()


def problems(pin, copy, get):
    """Why the copy is not upstream's file at the pinned commit; empty when it is."""
    commit = pin.get("parley_commit")
    if not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        return ["the pin names no full parley_commit to fetch"]
    found = []
    if hashlib.sha256(copy).hexdigest() != pin.get("sha256") or len(copy) != pin.get("bytes"):
        found.append("the local copy does not match its pin")
    try:
        upstream = get(upstream_url(pin))
    except Exception as exc:  # any failure to fetch: the check cannot pass without the bytes
        return [f"could not fetch {upstream_url(pin)}: {exc}"]
    digest = hashlib.sha256(upstream).hexdigest()
    if digest != pin.get("sha256") or len(upstream) != pin.get("bytes"):
        found.append(f"the pin does not match upstream at {commit}: upstream sha256 {digest}, {len(upstream)} bytes")
    if upstream != copy:
        found.append(f"the local copy is not upstream's file at {commit}")
    return found


def main():
    pin = json.loads((SCRIPTS / "parley_emit.pin.json").read_text())
    found = problems(pin, (SCRIPTS / "parley_emit.py").read_bytes(), lambda url: fetch(url, limit=pin.get("bytes")))
    for line in found:
        print(f"check_vendored_writer: {line}", file=sys.stderr)
    if not found:
        print(f"check_vendored_writer: parley_emit.py is upstream's file at {pin['parley_commit']} ({pin['sha256']})")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
