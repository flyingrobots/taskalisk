"""Inventory local worktrees, branches and GitHub work."""

from __future__ import annotations

import os
import re
from typing import Any

from .defaults import SHORT_SHA_LEN
from .github import gh_list_open_issues, gh_list_open_prs
from .process import run_cmd_checked, sanitize_home

# --------------------------------------------------------------------------- #
# Inventory (read-only)
# --------------------------------------------------------------------------- #


def collect_worktrees(repo: str, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    ok, raw, err = run_cmd_checked(["git", "worktree", "list", "--porcelain"], cwd=repo)
    if not ok:
        errors.append({"source": "git worktree list", "error": err or "command failed"})
        return []

    worktrees: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.strip():
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            wt_path = line[len("worktree ") :].strip()
            current["path"] = sanitize_home(wt_path)
            if not os.path.isdir(wt_path):
                current["path_exists"] = False
                current["dirty"] = None
                continue
            current["path_exists"] = True
            ok_st, dirty, err_st = run_cmd_checked(["git", "status", "--porcelain"], cwd=wt_path)
            if not ok_st:
                errors.append({"source": f"git status ({sanitize_home(wt_path)})", "error": err_st})
            current["dirty"] = bool(dirty) if ok_st else None
            ok_ab, ahead_behind, _ = run_cmd_checked(
                ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"], cwd=wt_path
            )
            if ok_ab and ahead_behind and "\t" in ahead_behind:
                a, b = ahead_behind.split("\t", 1)
                current["ahead_of_main"] = int(a)
                current["behind_main"] = int(b)
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
    if current:
        worktrees.append(current)
    return worktrees


def collect_unmerged_branches(
    repo: str, errors: list[dict[str, str]]
) -> dict[str, list[dict[str, Any]]]:
    ok_l, local_raw, err_l = run_cmd_checked(
        ["git", "branch", "--no-merged", "origin/main", "--format=%(refname:short)"], cwd=repo
    )
    if not ok_l:
        errors.append({"source": "git branch --no-merged", "error": err_l or "command failed"})
    ok_r, remote_raw, err_r = run_cmd_checked(
        ["git", "branch", "-r", "--no-merged", "origin/main", "--format=%(refname:short)"], cwd=repo
    )
    if not ok_r:
        errors.append({"source": "git branch -r --no-merged", "error": err_r or "command failed"})

    def summarize(branches: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for br in branches:
            if not br or br.endswith("/HEAD"):
                continue
            _, head, _ = run_cmd_checked(
                ["git", "rev-parse", f"--short={SHORT_SHA_LEN}", br], cwd=repo
            )
            ok_c, counts, _ = run_cmd_checked(
                ["git", "rev-list", "--left-right", "--count", f"{br}...origin/main"], cwd=repo
            )
            ahead = int(counts.split("\t")[0]) if ok_c and counts and "\t" in counts else None
            _, subject, _ = run_cmd_checked(["git", "log", "-n", "1", "--format=%s", br], cwd=repo)
            out.append({"branch": br, "head": head, "ahead_of_main": ahead, "tip_subject": subject})
        return out

    return {
        "local": summarize(local_raw.splitlines() if ok_l else []),
        "remote": summarize(remote_raw.splitlines() if ok_r else []),
    }


def collect_github_inventory(
    repo: str, milestone: str | None, errors: list[dict[str, str]]
) -> dict[str, Any]:
    prs = gh_list_open_prs(repo, errors)
    issues = gh_list_open_issues(repo, milestone, errors)
    summarized: list[dict[str, Any]] = []
    for iss in issues:
        labels = [lbl.get("name", "") for lbl in iss.get("labels", [])]
        summarized.append(
            {
                "number": iss["number"],
                "title": iss["title"],
                "milestone": (iss.get("milestone") or {}).get("title"),
                "labels": labels,
                "url": iss.get("url"),
            }
        )
    return {"open_prs": prs, "open_issues": summarized}


def list_branches(repo: str, errors: list[dict[str, str]]) -> list[str]:
    """Local and remote branch names; used only to point at recoverable work."""
    names: list[str] = []
    for cmd in (
        ["git", "branch", "--format=%(refname:short)"],
        ["git", "branch", "-r", "--format=%(refname:short)"],
    ):
        ok, raw, err = run_cmd_checked(cmd, cwd=repo)
        if not ok:
            errors.append({"source": " ".join(cmd[:3]), "error": err or "command failed"})
            continue
        names.extend(
            n.strip() for n in raw.splitlines() if n.strip() and not n.strip().endswith("/HEAD")
        )
    return sorted(set(names))


def branches_for_issue(number: int, branches: list[str]) -> list[str]:
    pattern = re.compile(rf"(?<!\d){number}(?!\d)")
    return [b for b in branches if pattern.search(b)]
