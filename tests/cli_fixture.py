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
    def setUp(self):
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

    def tearDown(self):
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

    def current(self):
        return json.loads(self.state.read_text())

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]

    def out(self, p):
        try:
            return json.loads(p.stdout)
        except json.JSONDecodeError:
            self.fail(f"not JSON (exit {p.returncode}): {p.stdout[:400]} {p.stderr[:400]}")

    @staticmethod
    def ids(r):
        return sorted(n["id"] for items in r["waves"].values() for n in items)

    @staticmethod
    def node(r, nid):
        return next(n for items in r["waves"].values() for n in items if n["id"] == nid)


class TrustFixture(Harness):
    """docs/threat-model.md controls C1-C5 and C18."""

    def untrusted_ids(self, r):
        return [u["id"] for u in r["source"]["untrusted_issues"]]
