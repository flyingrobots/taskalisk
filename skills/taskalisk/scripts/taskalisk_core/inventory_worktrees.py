"""Observe worktree paths and project Git porcelain fields without hiding read errors."""

from __future__ import annotations

import os

from .defaults import SHORT_SHA_LEN
from .inventory_values import Worktree
from .process import run_cmd_checked, sanitize_home


def _path_state(path: str, errors: list[dict[str, str]]) -> Worktree:
    """Distinguish a missing path, unknown status and a successfully observed clean checkout."""
    state: Worktree = {"path": sanitize_home(path)}
    if not os.path.isdir(path):
        state["path_exists"] = False
        state["dirty"] = None
        return state
    state["path_exists"] = True
    ok, dirty, error = run_cmd_checked(["git", "status", "--porcelain"], cwd=path)
    if not ok:
        errors.append({"source": f"git status ({sanitize_home(path)})", "error": error})
    state["dirty"] = bool(dirty) if ok else None
    available, counts, _ = run_cmd_checked(
        ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"], cwd=path
    )
    if available and counts and "\t" in counts:
        ahead, behind = counts.split("\t", 1)
        state["ahead_of_main"] = int(ahead)
        state["behind_main"] = int(behind)
    return state


def _record_field(current: Worktree, line: str, errors: list[dict[str, str]]) -> None:
    """Apply one recognized porcelain field, retaining record and observation order."""
    if line.startswith("worktree "):
        current.update(_path_state(line[len("worktree ") :].strip(), errors))
    elif line.startswith("HEAD "):
        current["head"] = line[len("HEAD ") :].strip()[:SHORT_SHA_LEN]
    elif line.startswith("branch "):
        current["branch"] = line[len("branch ") :].strip().removeprefix("refs/heads/")
    elif line == "detached":
        current["branch"] = "(detached HEAD)"
    elif line.startswith("prunable"):
        current["prunable"] = True
    elif line.startswith("locked"):
        current["locked"] = True


def collect_worktrees(repo: str, errors: list[dict[str, str]]) -> list[Worktree]:
    """Observe worktree paths, Git state and available divergence from origin/main."""
    ok, raw, error = run_cmd_checked(["git", "worktree", "list", "--porcelain"], cwd=repo)
    if not ok:
        errors.append({"source": "git worktree list", "error": error or "command failed"})
        return []
    worktrees: list[Worktree] = []
    current: Worktree = {}
    for line in raw.splitlines():
        if not line.strip():
            if current:
                worktrees.append(current)
                current = {}
            continue
        _record_field(current, line, errors)
    if current:
        worktrees.append(current)
    return worktrees
