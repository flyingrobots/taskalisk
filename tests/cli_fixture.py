"""Construct isolated CLI repositories and fake GitHub fixtures for offline tests."""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

SCRIPT = ROOT / "skills" / "taskalisk" / "scripts" / "taskalisk.py"

FAKE_GH = pathlib.Path(__file__).resolve().parent / "fake_gh.py"

HOME = "flyingrobots/geordi"

ECHO = "flyingrobots/echo"

BUNNY = "flyingrobots/bunny"


def fm(id_, kind="task", type_="feature", blocked_by=(), children=None, extra=""):
    lines = [".dag: issue-dag/2", f".id: {id_}", f".kind: {kind}"]
    if kind == "task":
        lines += [f".type: {type_}", ".blocked_by: [" + ", ".join(blocked_by) + "]"]
    if children is not None:
        lines.append(".children: [" + ", ".join(children) + "]")
    if extra:
        lines.append(extra)
    lines.append("area: notes are free")
    return "```yaml\n" + "\n".join(lines) + "\n```\n\n# Feature\n\nBody text.\n"


def issue(
    i, title, body, state="open", reason=None, author=None, association=None, editors=None, **extra
):
    out = {
        "id": i,
        "title": title,
        "state": state,
        "labels": [],
        "body": body,
        "state_reason": reason,
    }
    if author is not None:
        out["author"] = author
    if association is not None:
        out["association"] = association
    if editors is not None:
        out["editors"] = editors
    out.update(extra)
    return out


def closing(number, slug=HOME):
    owner, name = slug.split("/")
    return {"number": number, "repository": {"name": name, "owner": {"login": owner}}}


STRANGER = "mallory"


def plan_state():
    """Home roadmap #9 with children in three repositories; echo#6 blocks nothing at home."""
    return {
        "home": HOME,
        "blocked_by": {},
        "issues": {
            f"{HOME}#9": issue(
                109,
                "Roadmap",
                fm(
                    f"{HOME}#9",
                    kind="container",
                    children=[f"{HOME}#1", f"{HOME}#2", f"{ECHO}#5", f"{ECHO}#6", f"{HOME}#110"],
                ),
            ),
            f"{HOME}#1": issue(101, "Home one", fm(f"{HOME}#1", blocked_by=[f"{ECHO}#5"])),
            f"{HOME}#2": issue(102, "Home two", fm(f"{HOME}#2", blocked_by=[f"{HOME}#1"])),
            f"{HOME}#110": issue(110, "Home 110", fm(f"{HOME}#110", blocked_by=[f"{BUNNY}#110"])),
            f"{ECHO}#5": issue(5005, "Echo five", fm(f"{ECHO}#5", blocked_by=[f"{BUNNY}#7"])),
            f"{ECHO}#6": issue(5006, "Echo six", fm(f"{ECHO}#6", blocked_by=[f"{ECHO}#5"])),
            f"{BUNNY}#110": issue(9110, "Bunny 110, no frontmatter", "Plain body."),
            f"{BUNNY}#7": issue(
                9007, "Bunny seven, closed", fm(f"{BUNNY}#7"), state="closed", reason="completed"
            ),
        },
    }


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
