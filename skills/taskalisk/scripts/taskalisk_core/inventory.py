"""Inventory local worktrees, branches and GitHub work."""

from __future__ import annotations

import re

from .defaults import SHORT_SHA_LEN
from .github import gh_list_open_issues, gh_list_open_prs
from .inventory_values import Branch, BranchInventory, GithubInventory
from .inventory_worktrees import collect_worktrees as collect_worktrees
from .process import run_cmd_checked

# --------------------------------------------------------------------------- #
# Inventory (read-only)
# --------------------------------------------------------------------------- #


def collect_unmerged_branches(repo: str, errors: list[dict[str, str]]) -> BranchInventory:
    """Summarize local and remote branches not merged into origin/main."""
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

    def summarize(branches: list[str]) -> list[Branch]:
        out: list[Branch] = []
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
) -> GithubInventory:
    """Collect checked issue summaries and preserved PR inventory records."""
    prs = gh_list_open_prs(repo, errors)
    issues = gh_list_open_issues(repo, milestone, errors)
    return {"open_prs": [pr["wire"] for pr in prs], "open_issues": issues}


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
    """Find branch names containing the issue number without adjacent digits."""
    pattern = re.compile(rf"(?<!\d){number}(?!\d)")
    return [b for b in branches if pattern.search(b)]
