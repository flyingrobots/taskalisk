"""Scenarios whose output under the 1.x compiler is captured in tests/fixtures/golden/.

Each scenario is a fake_gh state and an argument vector. `capture_golden.py` ran them against
the compiler at flyingrobots/taskalisk@6e84058 (the last release of the single-document output)
and stored what it printed; `test_parley_output.py` runs them against the current compiler and
rebuilds the old document from the new lines. Changing a scenario invalidates its fixture: recapture
it from that commit, never edit the fixture by hand.
"""
import copy
import json
import os
import pathlib
import subprocess
import sys

from test_taskalisk import BUNNY, ECHO, HOME, STRANGER, closing, fm, issue, plan_state

FAKE_GH = pathlib.Path(__file__).resolve().parent / "fake_gh.py"
GOLDEN = pathlib.Path(__file__).resolve().parent / "fixtures" / "golden"
TMP_PLACEHOLDER = "<TMP>"


def rich_state():
    """One backlog that reaches every list the old document carried."""
    state = plan_state()
    state["collaborators"] = {HOME: ["owner"]}
    state["issues"][f"{HOME}#40"] = issue(140, "Legacy, no frontmatter", "No frontmatter here.")
    state["issues"][f"{HOME}#77"] = issue(177, "Stranger seed", fm(f"{HOME}#77"), author=STRANGER, association="NONE")
    state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=[f"{ECHO}#5", f"{ECHO}#99"], extra=".size_hours: 12")
    state["issues"][f"{ECHO}#99"] = issue(5099, "Dropped idea", fm(f"{ECHO}#99"), state="closed", reason="not_planned")
    state["issues"][f"{ECHO}#5"]["body"] = fm(f"{ECHO}#5", blocked_by=[f"{BUNNY}#7"], extra=".holds: [docs/]\n.meters: [gpu]")
    state["issues"][f"{HOME}#3"] = issue(103, "Home three", fm(f"{HOME}#3", extra=".holds: [docs/plans/]\n.meters: [gpu]"))
    state["issues"][f"{HOME}#4"] = issue(104, "Home four", fm(f"{HOME}#4", blocked_by=[f"{HOME}#1", f"{HOME}#2"], extra=".status: parked"))
    state["prs"] = [
        {"number": 8, "isDraft": True, "url": f"https://github.com/{HOME}/pull/8", "author": {"login": "owner"},
         "isCrossRepository": False, "closingIssuesReferences": [closing(3)]},
        {"number": 9, "isDraft": False, "url": f"https://github.com/{HOME}/pull/9", "author": {"login": STRANGER},
         "isCrossRepository": True, "closingIssuesReferences": [closing(2)]},
    ]
    return state


def violation_state():
    state = plan_state()
    state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=["#2"], extra=".blockedby: [x]")
    return state


def drift_state():
    state = plan_state()
    state["blocked_by"] = {f"{HOME}#2": [f"{HOME}#1"], f"{HOME}#1": [f"{BUNNY}#110"]}
    return state


def gh_failure_state():
    state = plan_state()
    state["fail_graphql"] = True
    return state


DAG_OK = {"merged": [f"{HOME}#0"], "nodes": {
    f"{HOME}#1": {"title": "a", "depends_on": [f"{HOME}#0"]},
    f"{HOME}#2": {"title": "b", "depends_on": [f"{HOME}#1", {"from": f"{HOME}#9", "isHard": False, "confidence": 0.4, "evidence": "maybe"}]},
    f"{HOME}#3": {"title": "c", "depends_on": [f"{HOME}#1", f"{HOME}#2"]}}}
DAG_CYCLE = {"nodes": {f"{HOME}#1": {"title": "a", "depends_on": [f"{HOME}#2"]}, f"{HOME}#2": {"title": "b", "depends_on": [f"{HOME}#1"]}}}

# name -> (state builder, argument vector, DAG spec or None). Arguments name no command: the 1.x
# compiler selected its mode by flag, and the current one infers the same command from them.
SCENARIOS = {
    "plan_root": (plan_state, ["--from-github", "--root", f"{HOME}#9"], None),
    "plan_home": (plan_state, ["--from-github"], None),
    "plan_rich": (rich_state, ["--from-github", "--sem-capacity", "gpu=1"], None),
    "plan_violations": (violation_state, ["--from-github", "--root", f"{HOME}#9"], None),
    "plan_compare": (drift_state, ["--from-github", "--root", f"{HOME}#9", "--compare-relationships"], None),
    "plan_gh_failure": (gh_failure_state, ["--from-github"], None),
    "edit_add": (plan_state, ["--from-github", "--root", f"{HOME}#9", "--add-edge", f"{ECHO}#6->{HOME}#2", "--reason", "contract first"], None),
    "edit_cycle": (plan_state, ["--from-github", "--root", f"{HOME}#9", "--add-edge", f"{HOME}#2->{ECHO}#5"], None),
    "verify_ok": (None, ["--verify-dag", "dag.json"], DAG_OK),
    "verify_cycle": (None, ["--verify-dag", "dag.json"], DAG_CYCLE),
    "inventory": (plan_state, [], None),
    "inventory_ok": (plan_state, [], None),
}
# Scenarios whose repository has a deterministic commit, an origin/main and one unmerged branch.
WITH_MAIN = {"inventory_ok"}
GIT_FIXED = {"GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
             "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


def seed_main(repo):
    env = dict(os.environ, **GIT_FIXED)
    git = ["git", "-c", "commit.gpgsign=false", "-C", str(repo)]
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "base"], check=True, env=env)
    subprocess.run(git + ["update-ref", "refs/remotes/origin/main", "HEAD"], check=True, env=env)
    subprocess.run(git + ["branch", "feature-2"], check=True, env=env)
    subprocess.run(git + ["checkout", "-q", "feature-2"], check=True, env=env)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "work on two"], check=True, env=env)
    subprocess.run(git + ["checkout", "-q", "main"], check=True, env=env)


def prepare(tmp):
    """A fake `gh` on PATH and a fresh git repository, as tests/test_taskalisk.py's Harness makes."""
    tmp = pathlib.Path(tmp)
    (tmp / "bin").mkdir()
    gh = tmp / "bin" / "gh"
    gh.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE_GH} \"$@\"\n")
    gh.chmod(0o755)
    (tmp / "repo").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp / "repo", check=True)
    (tmp / "gh.log").write_text("")
    return tmp


def run_scenario(script, name, tmp, extra_args=(), env_extra=None, cwd=None):
    """Run one scenario with `script` in a prepared `tmp`. Returns the CompletedProcess."""
    builder, args, dag = SCENARIOS[name]
    tmp = pathlib.Path(tmp)
    state = builder() if builder else {"home": HOME, "issues": {}, "blocked_by": {}}
    (tmp / "state.json").write_text(json.dumps(state))
    args = list(args)
    if name in WITH_MAIN and not (tmp / "repo" / ".git" / "refs" / "remotes").exists():
        seed_main(tmp / "repo")
    if dag is not None:
        (tmp / "dag.json").write_text(json.dumps(dag))
        args[args.index("dag.json")] = str(tmp / "dag.json")
    env = dict(os.environ, PATH=f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}",
               FAKE_GH_STATE=str(tmp / "state.json"), FAKE_GH_LOG=str(tmp / "gh.log"), **(env_extra or {}))
    return subprocess.run([sys.executable, str(script), "--repo", str(tmp / "repo"), *args, *extra_args],
                          capture_output=True, text=True, env=env, cwd=str(cwd or tmp))


def normalise(value, tmp):
    """Replace the temporary directory, which differs per run, with a placeholder."""
    text = json.dumps(value)
    for spelling in sorted({str(tmp), os.path.realpath(str(tmp))}, key=len, reverse=True):
        text = text.replace(spelling, TMP_PLACEHOLDER)
    return json.loads(text)


def load(name):
    return json.loads((GOLDEN / f"{name}.json").read_text())


def scenario_state(name):
    builder = SCENARIOS[name][0]
    return copy.deepcopy(builder()) if builder else None
