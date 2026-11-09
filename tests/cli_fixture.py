"""Construct isolated CLI repositories and fake GitHub fixtures for offline tests."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from fake_values import field, fields, items, records, text
from fixture_builders import (
    BUNNY as BUNNY,
)
from fixture_builders import (
    ECHO as ECHO,
)
from fixture_builders import (
    HOME as HOME,
)
from fixture_builders import (
    STRANGER as STRANGER,
)
from fixture_builders import (
    closing as closing,
)
from fixture_builders import (
    fm as fm,
)
from fixture_builders import (
    issue as issue,
)
from fixture_builders import (
    plan_state as plan_state,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]

SCRIPT = ROOT / "skills" / "taskalisk" / "scripts" / "taskalisk.py"

FAKE_GH = pathlib.Path(__file__).resolve().parent / "fake_gh.py"


class Harness(unittest.TestCase):
    """Own the temporary Git repository, fake provider state and observed output."""

    def setUp(self) -> None:
        """Create a fresh, isolated repository and provider shim for each test."""
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="taskalisk-test-"))
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "gh").write_text(f'#!/bin/sh\nexec {sys.executable} {FAKE_GH} "$@"\n')
        (self.bin / "gh").chmod(0o755)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        self.state = self.tmp / "state.json"
        self.log = self.tmp / "gh.log"
        self.log.write_text("")

    def tearDown(self) -> None:
        """Remove only this test's temporary files after its observations finish."""
        shutil.rmtree(self.tmp)

    def run_dag(self, state: object, *args: str) -> subprocess.CompletedProcess[str]:
        """Serialize an owned fixture and run the public CLI against the fake gh."""
        self.state.write_text(json.dumps(state))
        env = dict(
            os.environ,
            PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            FAKE_GH_STATE=str(self.state),
            FAKE_GH_LOG=str(self.log),
        )
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.repo), *args],
            capture_output=True,
            text=True,
            env=env,
        )

    def current_body(self, reference: str) -> str:
        """Read the persisted body independently of the compiler's response."""
        value: object = json.loads(self.state.read_text())
        return text(field(value, "issues", reference, "body"))

    def calls(self) -> list[list[str]]:
        """Require recorded argv arrays with text arguments in their original order."""
        calls: list[list[str]] = []
        for line in self.log.read_text().splitlines():
            if line.strip():
                value: object = json.loads(line)
                calls.append([text(arg) for arg in items(value)])
        return calls

    def out(self, p: subprocess.CompletedProcess[str]) -> dict[str, object]:
        """Check the response object without asserting a domain schema for its values."""
        try:
            value: object = json.loads(p.stdout)
        except json.JSONDecodeError:
            self.fail(f"not JSON (exit {p.returncode}): {p.stdout[:400]} {p.stderr[:400]}")
        return fields(value)

    @staticmethod
    def ids(r: dict[str, object]) -> list[str]:
        """Return every scheduled identifier; missing or malformed waves are failures."""
        return sorted(text(n["id"]) for wave in fields(r["waves"]).values() for n in records(wave))

    @staticmethod
    def node(r: dict[str, object], nid: str) -> dict[str, object]:
        """Require the requested node without synthesizing a missing result."""
        return next(
            n for wave in fields(r["waves"]).values() for n in records(wave) if n["id"] == nid
        )


class TrustFixture(Harness):
    """docs/threat-model.md controls C1-C5 and C18."""

    def untrusted_ids(self, r: dict[str, object]) -> list[str]:
        """Read the actual exclusion report; absent fields are a test failure."""
        return [text(u["id"]) for u in records(field(r, "source", "untrusted_issues"))]
