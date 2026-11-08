#!/usr/bin/env python3
"""
issue_dag_snapshot.py

Zero-local-state DAG compiler for the `issue-dag` skill. GitHub is the single
source of truth: issues are the tasks, native issue dependencies
(`blocked_by` / `blocking`) are the hard precedence edges, labels carry the
adjacent git-locks resource catalog, and GitHub's own timeline is the
provenance ledger. Nothing is cached or written on disk.

Modes:
  --from-github [--milestone v21.0.0] [--emit-mermaid]
      Read-only. Compiles the transitively-reduced DAG from open issues and
      their recorded `blocked_by` dependencies, ranks the Open Frontier, and
      proposes a prefix-aware conflict-free git-locks batch.
  --from-github --add-edge "#1080->#1052" [--reason "..."]
      Records a `blocked_by` dependency on GitHub (parent blocks child), then
      recompiles. If the new edge creates a cycle the dependency is removed
      again and the run fails.
  --from-github --remove-edge "#1080->#1052"
      Removes a recorded dependency.
  --verify-dag dag.json [--min-confidence 0.7] [--emit-mermaid]
      Read-only. Compiles a hand-written DAG specification (input, not state).
  --repo <path> [--milestone v21.0.0]
      Read-only. Full-spectrum inventory: worktrees, unmerged branches, open
      PRs, open issues. Exit 2 on any tool failure or possible truncation.

Guarantees:
1. DAG purity: only recorded GitHub dependencies enter the graph. Labels,
   shared files, and milestones never create edges.
2. Fail closed: any `gh`/`git` failure, unparseable JSON, or list result that
   fills its query limit is an error (exit 2), never an empty backlog.
3. Edges come with evidence: each edge cites the GitHub dependency record;
   each completed parent cites the closed issue's state and reason.
4. Lexical lock conflicts: git-locks keys are lexical; a trailing `/` claims a
   subtree, so `docs/` conflicts with `docs/plans/`.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

# Completed = GitHub closed. GitHub treats a closed blocker as satisfied,
# whatever the reason; "not_planned" parents are reported separately.
COMPLETED_STATUSES = {"merged", "closed", "done", "completed"}
IN_FLIGHT_STATUSES = {"ready-to-merge", "in-progress", "active"}
FRONTIER_STATUS = "open-frontier"
BLOCKED_STATUS = "blocked"

MERGED_HINT = "(merged)"
DEFAULT_MIN_CONFIDENCE = 0.7
DENSITY_BAND = (0.01, 0.50)
GH_ISSUE_LIST_LIMIT = 1000
GH_PR_LIST_LIMIT = 500
SHORT_SHA_LEN = 9
MERMAID_TITLE_MAX = 48

PRIORITY_IN_FLIGHT_WEIGHT = 1000
# Parked work has a recoverable branch: resuming it costs less than starting
# fresh, so it ranks above untouched work but below work already in flight.
PRIORITY_PARKED_WEIGHT = 500
PRIORITY_DESCENDANTS_WEIGHT = 100
PRIORITY_DEPTH_WEIGHT = 10

CONTAINER_LABEL = "type:goalpost"
ACTIVE_LABEL = "status:active"
PARKED_LABEL = "status:parked"
BLOCKED_LABEL = "status:blocked"
PARKED_STATUS = "parked"

# House card standard for issue bodies (the issue body is the task plan).
HOUSE_CARD_TYPES = {"Feature", "Bug", "Decision", "Investigation", "Research", "Spike"}
HOUSE_H1_RE = re.compile(r"^#\s+(Feature|Bug|Decision|Investigation|Research|Spike)\s*$", re.MULTILINE)
HOUSE_PROMPT_FENCE = "```text"
HOUSE_SECTION_NUMBERS = range(1, 10)
HOUSE_PATH_RE = re.compile(r"(?<![\w/])/(Users|home)/[A-Za-z0-9_.-]+/")
LOCK_LABEL_PREFIX = "lock:"
TYPE_LABEL_PREFIX = "type:"
AREA_LABEL_PREFIX = "area:"
# Adjacent resource default when no `lock:*` label is present.
AREA_TO_LOCK = {
    "area:docs": "docs/",
    "area:tooling": "scripts/",
    "area:release": "docs/",
}
DEFAULT_LOCK = "host/heavy-work"


def strip_merged_hint(ref: str) -> str:
    return ref.replace(MERGED_HINT, "").strip()


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


def collect_unmerged_branches(repo: str, errors: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
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
            _, head, _ = run_cmd_checked(["git", "rev-parse", f"--short={SHORT_SHA_LEN}", br], cwd=repo)
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


def gh_list_open_prs(repo: str, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    cmd = [
        "gh", "pr", "list", "--state", "open", "--limit", str(GH_PR_LIST_LIMIT),
        "--json", "number,title,headRefName,isDraft,url,closingIssuesReferences",
    ]
    ok, raw, err = run_cmd_checked(cmd, cwd=repo)
    if not ok:
        errors.append({"source": "gh pr list", "error": err or "command failed"})
        return []
    prs = parse_json_list(raw, "gh pr list", errors)
    if len(prs) >= GH_PR_LIST_LIMIT:
        errors.append({"source": "gh pr list", "error": f"Result filled --limit {GH_PR_LIST_LIMIT}; possible truncation"})
    return prs


def gh_list_open_issues(repo: str, milestone: str | None, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    cmd = [
        "gh", "issue", "list", "--state", "open", "--limit", str(GH_ISSUE_LIST_LIMIT),
        "--json", "number,title,labels,milestone,url,body",
    ]
    if milestone:
        cmd.extend(["--milestone", milestone])
    ok, raw, err = run_cmd_checked(cmd, cwd=repo)
    if not ok:
        errors.append({"source": "gh issue list", "error": err or "command failed"})
        return []
    issues = parse_json_list(raw, "gh issue list", errors)
    if len(issues) >= GH_ISSUE_LIST_LIMIT:
        errors.append({"source": "gh issue list", "error": f"Result filled --limit {GH_ISSUE_LIST_LIMIT}; possible truncation"})
    return issues


def collect_github_inventory(repo: str, milestone: str | None, errors: list[dict[str, str]]) -> dict[str, Any]:
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
                "is_container": CONTAINER_LABEL in labels,
                "url": iss.get("url"),
            }
        )
    return {"open_prs": prs, "open_issues": summarized}


# --------------------------------------------------------------------------- #
# GitHub-native DAG source
# --------------------------------------------------------------------------- #


def gh_repo_slug(repo: str, errors: list[dict[str, str]]) -> str | None:
    ok, raw, err = run_cmd_checked(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=repo)
    if not ok or not raw:
        errors.append({"source": "gh repo view", "error": err or "command failed"})
        return None
    return raw


def gh_blocked_by(repo: str, slug: str, number: int, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Return the issues that block `number`, via GitHub's native dependency API."""
    ok, raw, err = run_cmd_checked(
        ["gh", "api", "--paginate", f"repos/{slug}/issues/{number}/dependencies/blocked_by"], cwd=repo
    )
    if not ok:
        errors.append({"source": f"gh api repos/{slug}/issues/{number}/dependencies/blocked_by", "error": err or "command failed"})
        return []
    # --paginate concatenates arrays as separate JSON documents; split them.
    items: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    idx = 0
    text = raw.strip()
    while idx < len(text):
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError as exc:
            errors.append({"source": f"gh api repos/{slug}/issues/{number}/dependencies/blocked_by", "error": f"Unparseable JSON: {exc}"})
            return []
        if isinstance(obj, list):
            items.extend(obj)
        idx = end
        while idx < len(text) and text[idx].isspace():
            idx += 1
    return items


def gh_issue_database_id(repo: str, slug: str, number: int, errors: list[dict[str, str]]) -> int | None:
    ok, raw, err = run_cmd_checked(["gh", "api", f"repos/{slug}/issues/{number}", "--jq", ".id"], cwd=repo)
    if not ok or not raw:
        errors.append({"source": f"gh api repos/{slug}/issues/{number}", "error": err or "command failed"})
        return None
    return int(raw)


IssueRef = tuple[str, int]  # (owner/repo slug, issue number)
ISSUE_REF_RE = re.compile(r"\s*(?:(?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#|#?)(?P<num>\d+)\s*")
REPOSITORY_URL_RE = re.compile(r"/repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/?$")


def node_id(slug: str, number: int, home: str) -> str:
    """Canonical node id: '#123' in the home repository, 'owner/repo#123' elsewhere."""
    return f"#{number}" if slug == home else f"{slug}#{number}"


def parse_issue_ref(text: str, home: str) -> IssueRef | None:
    """Parse '#123' or '123' (home repository) or 'owner/repo#123' (any repository)."""
    m = ISSUE_REF_RE.fullmatch(text)
    if not m:
        return None
    return (m.group("slug") or home, int(m.group("num")))


def parse_edge_arg(arg: str, home: str) -> tuple[IssueRef, IssueRef] | None:
    """'#1080->owner/repo#1052' means #1080 blocks owner/repo#1052 (parent -> child)."""
    parts = arg.split("->")
    if len(parts) != 2:
        return None
    parent, child = parse_issue_ref(parts[0], home), parse_issue_ref(parts[1], home)
    if parent is None or child is None:
        return None
    return parent, child


def slug_from_repository_url(url: str) -> str | None:
    m = REPOSITORY_URL_RE.search(url or "")
    return m.group(1) if m else None


def id_sort_key(nid: str) -> tuple[str, int]:
    """Home ids ('#12') sort first, then other repositories by slug, each by number."""
    slug, _, num = nid.rpartition("#")
    return (slug, int(num) if num.isdigit() else 0)


def lock_keys_from_labels(labels: list[str]) -> tuple[list[str], str]:
    explicit = sorted({lbl[len(LOCK_LABEL_PREFIX):] for lbl in labels if lbl.startswith(LOCK_LABEL_PREFIX)})
    if explicit:
        return explicit, "lock-label"
    for area, key in AREA_TO_LOCK.items():
        if area in labels:
            return [key], f"derived-from-{area}"
    return [DEFAULT_LOCK], "default"


def first_label(labels: list[str], prefix: str) -> str:
    """Deterministic choice: the lexicographically first label on the axis (GitHub's order is not stable)."""
    for lbl in sorted(labels):
        if lbl.startswith(prefix):
            return lbl[len(prefix):]
    return ""


LABEL_AXES = (TYPE_LABEL_PREFIX, "priority:", "status:", AREA_LABEL_PREFIX)


def label_axis_violations(labels: list[str]) -> dict[str, list[str]]:
    """Axes that do not carry exactly one label (AGENTS.md: exactly one per axis)."""
    out: dict[str, list[str]] = {}
    for axis in LABEL_AXES:
        on_axis = sorted(lbl for lbl in labels if lbl.startswith(axis))
        if len(on_axis) != 1:
            out[axis.rstrip(":")] = on_axis
    return out


def house_format_violations(body: str) -> list[str]:
    """
    Check an issue body against the house card standard: a `# <Type>` heading,
    a fenced ```text LLM execution prompt, the nine numbered sections, and no
    machine-local absolute paths.
    """
    problems: list[str] = []
    text = body or ""
    if not HOUSE_H1_RE.search(text):
        problems.append("missing '# <Feature|Bug|Decision|Investigation|Research|Spike>' heading")
    if HOUSE_PROMPT_FENCE not in text:
        problems.append("missing fenced ```text LLM execution prompt block")
    missing = [str(n) for n in HOUSE_SECTION_NUMBERS if not re.search(rf"^##\s+{n}\.\s", text, re.MULTILINE)]
    if missing:
        problems.append(f"missing numbered sections: {', '.join(missing)}")
    if HOUSE_PATH_RE.search(text):
        problems.append("contains a machine-local absolute path")
    return problems


def list_branches(repo: str, errors: list[dict[str, str]]) -> list[str]:
    """Local and remote branch names; used only to point at recoverable work."""
    names: list[str] = []
    for cmd in (["git", "branch", "--format=%(refname:short)"], ["git", "branch", "-r", "--format=%(refname:short)"]):
        ok, raw, err = run_cmd_checked(cmd, cwd=repo)
        if not ok:
            errors.append({"source": " ".join(cmd[:3]), "error": err or "command failed"})
            continue
        names.extend(n.strip() for n in raw.splitlines() if n.strip() and not n.strip().endswith("/HEAD"))
    return sorted(set(names))


def branches_for_issue(number: int, branches: list[str]) -> list[str]:
    pattern = re.compile(rf"(?<!\d){number}(?!\d)")
    return [b for b in branches if pattern.search(b)]


def collect_github_dag(repo: str, milestone: str | None, errors: list[dict[str, str]]) -> dict[str, Any]:
    """
    Build (merged, nodes) from GitHub only. Open issues (minus containers) are
    nodes. For every node, its recorded `blocked_by` issues become edges: an
    open blocker is a hard edge (and becomes a node itself, even outside the
    milestone filter, because precedence is about correctness, not scope); a
    closed blocker is a completed parent.
    """
    slug = gh_repo_slug(repo, errors)
    if slug is None:
        return {"merged": set(), "nodes": {}, "containers": [], "external_open_blockers": [], "not_planned_parents": [], "in_flight_prs": {}}

    issues = gh_list_open_issues(repo, milestone, errors)
    prs = gh_list_open_prs(repo, errors)
    branches = list_branches(repo, errors)
    if errors:
        return {"merged": set(), "nodes": {}, "containers": [], "external_open_blockers": [], "not_planned_parents": [], "in_flight_prs": {}}

    prs_by_issue: dict[IssueRef, list[dict[str, Any]]] = defaultdict(list)
    for pr in prs:
        for ref in pr.get("closingIssuesReferences", []) or []:
            if isinstance(ref, dict) and "number" in ref:
                repo_info = ref.get("repository") or {}
                owner = (repo_info.get("owner") or {}).get("login")
                ref_slug = f"{owner}/{repo_info['name']}" if owner and repo_info.get("name") else slug
                prs_by_issue[(ref_slug, int(ref["number"]))].append({"number": pr["number"], "isDraft": pr.get("isDraft", False), "url": pr.get("url")})

    containers: list[dict[str, Any]] = []
    seed: dict[IssueRef, dict[str, Any]] = {}
    for iss in issues:
        labels = [lbl.get("name", "") for lbl in iss.get("labels", [])]
        if CONTAINER_LABEL in labels:
            containers.append({"id": node_id(slug, int(iss["number"]), slug), "number": iss["number"], "title": iss["title"]})
            continue
        seed[(slug, int(iss["number"]))] = {"title": iss["title"], "labels": labels, "url": iss.get("url"), "milestone": (iss.get("milestone") or {}).get("title"), "in_filter": True, "body": iss.get("body") or ""}

    nodes: dict[str, dict[str, Any]] = {}
    merged: set[str] = set()
    not_planned_parents: list[dict[str, Any]] = []
    external_open_blockers: list[dict[str, Any]] = []
    container_blockers: list[dict[str, Any]] = []
    queue: deque[IssueRef] = deque(sorted(seed))
    known: dict[IssueRef, dict[str, Any]] = dict(seed)

    while queue:
        ref = queue.popleft()
        ref_slug, number = ref
        nid = node_id(ref_slug, number, slug)
        meta = known[ref]
        blockers = gh_blocked_by(repo, ref_slug, number, errors)
        if errors:
            break
        depends_on: list[dict[str, Any]] = []
        for blk in blockers:
            b_num = int(blk["number"])
            b_slug = slug_from_repository_url(str(blk.get("repository_url") or ""))
            if b_slug is None:
                # Without the repository, the blocker id is ambiguous; fail closed.
                errors.append({"source": f"gh api repos/{ref_slug}/issues/{number}/dependencies/blocked_by", "error": f"Blocker #{b_num} has no parseable repository_url"})
                break
            b_ref = (b_slug, b_num)
            bid = node_id(b_slug, b_num, slug)
            b_labels = [lbl.get("name", "") for lbl in blk.get("labels", [])]
            b_state = str(blk.get("state", "")).lower()
            evidence = f"GitHub dependency: {bid} blocks {nid} ({blk.get('html_url') or 'repos/' + ref_slug + '/issues/' + str(number) + '/dependencies/blocked_by'})"
            if b_state == "closed":
                merged.add(bid)
                reason = str(blk.get("state_reason") or "completed")
                if reason == "not_planned":
                    not_planned_parents.append({"parent": bid, "child": nid, "title": blk.get("title", "")})
                depends_on.append({"from": f"{bid} {MERGED_HINT}", "type": "recorded", "isHard": True, "confidence": 1.0, "evidence": f"{evidence}; closed as {reason}"})
                continue
            if CONTAINER_LABEL in b_labels:
                # A container never blocks anything structurally, so the edge
                # leaves the DAG; record it so the drop is visible, not silent.
                container_blockers.append({"container": bid, "blocks": nid, "title": blk.get("title", "")})
                continue
            depends_on.append({"from": bid, "type": "recorded", "isHard": True, "confidence": 1.0, "evidence": evidence})
            if b_ref not in known:
                known[b_ref] = {"title": blk.get("title", ""), "labels": b_labels, "url": blk.get("html_url"), "milestone": (blk.get("milestone") or {}).get("title"), "in_filter": False, "body": blk.get("body") or ""}
                external_open_blockers.append({"id": bid, "number": b_num, "repository": b_slug, "title": blk.get("title", ""), "milestone": known[b_ref]["milestone"], "blocks": nid})
                queue.append(b_ref)
        if errors:
            break

        labels = meta["labels"]
        linked = prs_by_issue.get(ref, [])
        if ACTIVE_LABEL in labels or linked:
            status = "in-progress"
        elif PARKED_LABEL in labels:
            status = PARKED_STATUS
        elif BLOCKED_LABEL in labels:
            # A hand-set block (often an external or decision wait). Never
            # dispatched; contradictions with the graph are reported below.
            status = BLOCKED_STATUS
        else:
            status = "open"
        open_blockers = sum(1 for d in depends_on if MERGED_HINT not in str(d.get("from", "")))
        label_status = sorted(lbl for lbl in labels if lbl.startswith("status:"))
        locks, lock_source = lock_keys_from_labels(labels)
        nodes[nid] = {
            "title": meta["title"],
            "type": first_label(labels, TYPE_LABEL_PREFIX) or "untyped",
            "workstream": first_label(labels, AREA_LABEL_PREFIX) or "unassigned",
            "status": status,
            "depends_on": depends_on,
            "resources": locks,
            "resource_source": lock_source,
            "linked_open_prs": linked,
            "recoverable_branches": branches_for_issue(number, branches) if ref_slug == slug else [],
            "house_format_violations": house_format_violations(meta.get("body", "")),
            "label_axis_violations": label_axis_violations(labels),
            "status_labels": label_status,
            "open_blocker_count": open_blockers,
            "url": meta.get("url"),
            "milestone": meta.get("milestone"),
            "in_filter": meta.get("in_filter", True),
        }

    return {
        "merged": merged,
        "nodes": nodes,
        "containers": containers,
        "external_open_blockers": external_open_blockers,
        "not_planned_parents": not_planned_parents,
        "container_blockers": container_blockers,
        "slug": slug,
    }


def label_audit(nodes: dict[str, dict[str, Any]], merged: set[str]) -> dict[str, Any]:
    """Contradictions between hand-set labels and the GitHub graph; reported, never silently resolved."""
    axis: dict[str, Any] = {}
    status_conflicts: list[dict[str, Any]] = []
    for nid, meta in sorted(nodes.items()):
        if nid in merged:
            continue
        if meta.get("label_axis_violations"):
            axis[nid] = meta["label_axis_violations"]
        labels = meta.get("status_labels", [])
        n_open = meta.get("open_blocker_count", 0)
        if BLOCKED_LABEL in labels and n_open == 0:
            status_conflicts.append({"id": nid, "labels": labels, "open_blockers": 0, "problem": "status:blocked but no open GitHub blocker"})
        elif n_open > 0 and (ACTIVE_LABEL in labels or "status:available" in labels):
            status_conflicts.append({"id": nid, "labels": labels, "open_blockers": n_open, "problem": "open GitHub blockers but not status:blocked"})
    return {"label_axis_violations": axis, "status_label_conflicts": status_conflicts}


# --------------------------------------------------------------------------- #
# DAG compiler
# --------------------------------------------------------------------------- #


def normalize_dep_entry(dep: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(dep, str):
        return {"from": strip_merged_hint(dep), "type": "accepted", "isHard": True, "confidence": 1.0, "evidence": "Declared in DAG specification", "merged_hint": MERGED_HINT in dep}
    raw_from = str(dep.get("from", ""))
    return {
        "from": strip_merged_hint(raw_from),
        "type": str(dep.get("type", "accepted")),
        "isHard": bool(dep.get("isHard", True)),
        "confidence": float(dep.get("confidence", 1.0)),
        "evidence": str(dep.get("evidence", "Declared in DAG specification")),
        "merged_hint": MERGED_HINT in raw_from,
    }


def lock_keys_conflict(a: str, b: str) -> bool:
    if a == b:
        return True
    a_tree = a if a.endswith("/") else a + "/"
    b_tree = b if b.endswith("/") else b + "/"
    return a_tree.startswith(b_tree) or b_tree.startswith(a_tree)


def any_lock_conflict(required: set[str], held: set[str]) -> bool:
    return any(lock_keys_conflict(r, h) for r in required for h in held)


def compile_and_analyze_dag(merged: set[str], nodes: dict[str, dict[str, Any]], min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> dict[str, Any]:
    merged = set(merged)
    for nid, meta in nodes.items():
        if str(meta.get("status", "")).strip().lower() in COMPLETED_STATUSES:
            merged.add(nid)

    open_nodes = sorted(nid for nid in nodes if nid not in merged)
    open_set = set(open_nodes)

    raw_children: dict[str, set[str]] = defaultdict(set)
    raw_parents: dict[str, set[str]] = defaultdict(set)
    completed_parents: dict[str, list[str]] = defaultdict(list)
    edge_evidence: dict[tuple[str, str], str] = {}
    soft_edges: list[dict[str, Any]] = []
    unknown: list[dict[str, str]] = []
    stale_hints: list[dict[str, str]] = []

    for nid in open_nodes:
        for raw_dep in nodes[nid].get("depends_on", nodes[nid].get("prerequisites", [])):
            edge = normalize_dep_entry(raw_dep)
            parent = edge["from"]
            if not parent:
                continue
            if not edge["isHard"] or edge["confidence"] < min_confidence:
                soft_edges.append({"from": parent, "to": nid, "type": edge["type"], "isHard": edge["isHard"], "confidence": edge["confidence"], "evidence": edge["evidence"]})
                continue
            if edge["merged_hint"] and parent in open_set:
                stale_hints.append({"node": nid, "prerequisite": parent, "prerequisite_status": str(nodes[parent].get("status", "open"))})
                continue
            if parent in merged or edge["merged_hint"]:
                merged.add(parent)
                if parent not in completed_parents[nid]:
                    completed_parents[nid].append(parent)
            elif parent in open_set:
                raw_parents[nid].add(parent)
                raw_children[parent].add(nid)
                edge_evidence[(parent, nid)] = edge["evidence"]
            else:
                unknown.append({"node": nid, "unknown_prerequisite": parent})

    if unknown or stale_hints:
        return {"ok": False, "error": "Unresolved prerequisites: unknown references and/or stale (merged) hints", "unknown_dependencies": unknown, "stale_merged_hints": stale_hints, "soft_or_low_confidence_edges": soft_edges}

    in_deg = {nid: len(raw_parents[nid]) for nid in open_nodes}
    queue: deque[str] = deque([nid for nid, d in in_deg.items() if d == 0])
    topo: list[str] = []
    while queue:
        u = queue.popleft()
        topo.append(u)
        for v in sorted(raw_children.get(u, ())):
            if v in in_deg:
                in_deg[v] -= 1
                if in_deg[v] == 0:
                    queue.append(v)
    if len(topo) != len(open_nodes):
        return {"ok": False, "error": "Cycle detected in hard structural edges", "cyclic_nodes": [n for n, d in in_deg.items() if d > 0], "unknown_dependencies": [], "stale_merged_hints": []}

    descendants: dict[str, set[str]] = {nid: set() for nid in open_nodes}
    for u in reversed(topo):
        for v in raw_children.get(u, ()):
            if v in open_set:
                descendants[u].add(v)
                descendants[u].update(descendants[v])

    reduced_children: dict[str, list[str]] = defaultdict(list)
    reduced_parents: dict[str, list[str]] = defaultdict(list)
    redundant: list[dict[str, str]] = []
    for u in open_nodes:
        children_u = sorted(raw_children.get(u, set()) & open_set)
        for v in children_u:
            via = [w for w in children_u if w != v and v in descendants[w]]
            if via:
                redundant.append({"from": u, "to": v, "implied_via": via[0]})
            else:
                reduced_children[u].append(v)
                reduced_parents[v].append(u)

    level: dict[str, int] = {}
    pred: dict[str, str | None] = {}
    for u in topo:
        if not reduced_parents[u]:
            level[u], pred[u] = 0, None
        else:
            best = max(reduced_parents[u], key=lambda p: (level[p], p))
            level[u], pred[u] = level[best] + 1, best

    remaining: dict[str, int] = {}
    for u in reversed(topo):
        remaining[u] = 1 if not reduced_children[u] else 1 + max(remaining[v] for v in reduced_children[u])

    critical_path: list[str] = []
    if open_nodes:
        curr: str | None = max(open_nodes, key=lambda n: (level[n], n))
        while curr is not None:
            critical_path.append(curr)
            curr = pred.get(curr)
        critical_path.reverse()

    n_open = len(open_nodes)
    e_raw = sum(len(raw_children[u] & open_set) for u in open_nodes)
    e_red = sum(len(reduced_children[u]) for u in open_nodes)
    max_edges = (n_open * (n_open - 1)) / 2 if n_open > 1 else 1
    density = round(e_red / max_edges, 4) if n_open > 1 else 0.0

    waves: dict[int, list[dict[str, Any]]] = defaultdict(list)
    isolated: list[str] = []
    for nid in open_nodes:
        meta = nodes[nid]
        if not reduced_parents[nid] and not reduced_children[nid]:
            isolated.append(nid)
        status = str(meta.get("status", "open")).strip().lower()
        in_flight = 1 if status in IN_FLIGHT_STATUSES else 0
        parked = 1 if status == PARKED_STATUS else 0
        score = (
            in_flight * PRIORITY_IN_FLIGHT_WEIGHT
            + parked * PRIORITY_PARKED_WEIGHT
            + len(descendants[nid]) * PRIORITY_DESCENDANTS_WEIGHT
            + remaining[nid] * PRIORITY_DEPTH_WEIGHT
            + len(reduced_children[nid])
        )
        resources = meta.get("resources") or [DEFAULT_LOCK]
        waves[level[nid]].append(
            {
                "id": nid,
                "title": meta.get("title", ""),
                "url": meta.get("url"),
                "type": meta.get("type", ""),
                "workstream": meta.get("workstream", ""),
                "milestone": meta.get("milestone"),
                "in_filter": meta.get("in_filter", True),
                "status": status,
                "derived_status": FRONTIER_STATUS if level[nid] == 0 else BLOCKED_STATUS,
                "linked_open_prs": meta.get("linked_open_prs", []),
                "recoverable_branches": meta.get("recoverable_branches", []),
                "house_format_violations": meta.get("house_format_violations", []),
                "completed_parents": sorted(completed_parents[nid]),
                "open_parents": sorted(reduced_parents[nid]),
                "directly_unlocks": sorted(reduced_children[nid]),
                "transitive_unblocks_count": len(descendants[nid]),
                "critical_path_remaining_depth": remaining[nid],
                "priority_score": score,
                "resources": sorted(set(resources)),
                "resource_source": meta.get("resource_source", "spec"),
            }
        )
    for lvl in waves:
        waves[lvl].sort(key=lambda item: (-item["priority_score"], item["id"]))

    frontier = waves.get(0, [])
    held: set[str] = set()
    batch: list[dict[str, Any]] = []
    for cand in frontier:
        if cand["status"] == BLOCKED_STATUS:
            continue  # hand-set block: never dispatched, even with no graph blocker
        req = set(cand["resources"])
        if not any_lock_conflict(req, held):
            held.update(req)
            batch.append({"id": cand["id"], "title": cand["title"], "url": cand.get("url"), "workstream": cand["workstream"], "priority_score": cand["priority_score"], "canonical_locks": sorted(req)})

    lo, hi = DENSITY_BAND
    return {
        "ok": True,
        "metrics": {
            "merged_count": len(merged),
            "open_node_count": n_open,
            "raw_open_edge_count": e_raw,
            "reduced_open_edge_count": e_red,
            "transitive_redundant_edges_removed_count": len(redundant),
            "edge_density": density,
            "edge_density_band_ok": lo <= density <= hi if n_open > 1 else True,
            "max_parallel_width": max((len(w) for w in waves.values()), default=0),
            "critical_path_length": len(critical_path),
            "critical_path": critical_path,
            "isolated_open_node_count": len(isolated),
            "isolated_open_nodes": isolated,
        },
        "edges": [{"from": u, "to": v, "evidence": edge_evidence.get((u, v), "")} for u in open_nodes for v in reduced_children[u]],
        "transitive_redundant_edges_removed": redundant,
        "soft_or_low_confidence_edges": soft_edges,
        "unknown_dependencies": [],
        "stale_merged_hints": [],
        "open_frontier_count": len(frontier),
        "open_frontier_ranked": frontier,
        "conflict_free_frontier_batch": batch,
        "waves": {f"Wave {k}": waves[k] for k in sorted(waves)},
    }


def render_mermaid_flowchart(dag_result: dict[str, Any]) -> str:
    waves: dict[str, list[dict[str, Any]]] = dag_result.get("waves", {})

    def safe_id(raw: str) -> str:
        return "N_" + re.sub(r"[^A-Za-z0-9_]", "_", raw)

    lines = ["flowchart TD"]
    edges: list[tuple[str, str]] = []
    for wave_name, items in waves.items():
        sg = re.sub(r"[^A-Za-z0-9_]", "", wave_name)
        label = f"{wave_name}: Open Frontier (Zero Incomplete Parents)" if wave_name == "Wave 0" else wave_name
        lines.append(f'  subgraph {sg}["{label}"]')
        for item in items:
            nid = item["id"]
            title = item.get("title", "")
            if len(title) > MERMAID_TITLE_MAX:
                title = title[: MERMAID_TITLE_MAX - 3] + "..."
            safe_label = f"{nid}: {title}".replace('"', "'").replace("<", "(").replace(">", ")")
            lines.append(f'    {safe_id(nid)}["{safe_label}"]')
            for child in item.get("directly_unlocks", []):
                edges.append((safe_id(nid), safe_id(child)))
        lines.append("  end")
    for s, d in edges:
        lines.append(f"  {s} --> {d}")
    return "\n".join(lines)


ROADMAP_BEGIN = "<!-- BEGIN GENERATED ISSUE DAG (issue-dag --emit-roadmap; do not edit by hand) -->"
ROADMAP_END = "<!-- END GENERATED ISSUE DAG -->"


def _issue_link(nid: str, url: str | None) -> str:
    return f"[{nid}]({url})" if url else nid


def _md_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_roadmap_block(result: dict[str, Any]) -> str:
    """Render the computed ROADMAP sections. Pure function of the compiled DAG."""
    m = result["metrics"]
    src = result.get("source", {})
    waves: dict[str, list[dict[str, Any]]] = result["waves"]
    by_id = {n["id"]: n for items in waves.values() for n in items}
    out: list[str] = [ROADMAP_BEGIN, ""]
    out += [
        f"Compiled from GitHub `{src.get('repository', '')}` milestone `{src.get('milestone_filter') or 'all'}`. "
        f"Artifact hash `{result.get('meta', {}).get('artifact_hash', '')[:16]}`. "
        "Regenerate with `issue_dag_snapshot.py --from-github --milestone <m> --emit-roadmap`.",
        "",
        "## DAG Structural Health",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Open nodes | {m['open_node_count']} |",
        f"| Reduced edges (raw) | {m['reduced_open_edge_count']} ({m['raw_open_edge_count']}) |",
        f"| Edge density | {m['edge_density']} ({'in' if m['edge_density_band_ok'] else 'outside'} band 0.01–0.50) |",
        f"| Max parallel width | {m['max_parallel_width']} |",
        f"| Critical path ({m['critical_path_length']}) | {' → '.join(m['critical_path'])} |",
        f"| Isolated nodes | {m['isolated_open_node_count']} |",
        f"| Containers excluded | {', '.join(c.get('id') or '#' + str(c['number']) for c in src.get('containers_excluded', [])) or 'none'} |",
        "",
        "## Ranked Open Frontier (Wave 0)",
        "",
        "| Rank | Score | Issue | Title | Status | Unblocks | Depth | Locks | Directly unlocks |",
        "| ---: | ---: | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for i, n in enumerate(result.get("open_frontier_ranked", []), 1):
        out.append(
            f"| {i} | {n['priority_score']} | {_issue_link(n['id'], n.get('url'))} | {_md_cell(n['title'])} | {n['status']} | "
            f"{n['transitive_unblocks_count']} | {n['critical_path_remaining_depth']} | {', '.join(f'`{k}`' for k in n['resources'])} | "
            f"{', '.join(n['directly_unlocks']) or '—'} |"
        )
    out += ["", "### Conflict-Free git-locks Batch", ""]
    for b in result.get("conflict_free_frontier_batch", []):
        out.append(f"- {_issue_link(b['id'], b.get('url'))} {_md_cell(b['title'])} — {', '.join(f'`{k}`' for k in b['canonical_locks'])}")
    out += ["", "## Task Checklist by Wave", ""]
    for wname, items in waves.items():
        out += [f"### {wname}", ""]
        for n in items:
            out.append(f"- [ ] {_issue_link(n['id'], n.get('url'))} {_md_cell(n['title'])} ({n['status']})")
        out.append("")
    out += ["## Task Checklist by Workstream (`area:*`)", ""]
    streams: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n in by_id.values():
        streams[n.get("workstream") or "unassigned"].append(n)
    for ws in sorted(streams):
        out += [f"### {ws}", ""]
        for n in sorted(streams[ws], key=lambda x: id_sort_key(x["id"])):
            out.append(f"- [ ] {_issue_link(n['id'], n.get('url'))} {_md_cell(n['title'])}")
        out.append("")
    out += ["## Transitively-Reduced Dependency DAG", "", "```mermaid", render_mermaid_flowchart(result), "```", ""]
    out += ["## Prerequisite Edge Accounting", "", "| Blocker | Blocked | Evidence |", "| --- | --- | --- |"]
    for e in result.get("edges", []):
        out.append(f"| {e['from']} | {e['to']} | {_md_cell(e['evidence'])} |")
    if result.get("transitive_redundant_edges_removed"):
        out += ["", "Recorded on GitHub but implied by a longer path (kept there as evidence, omitted from the reduced DAG):", ""]
        for e in result["transitive_redundant_edges_removed"]:
            out.append(f"- {e['from']} → {e['to']} (via {e['implied_via']})")
    out += ["", ROADMAP_END]
    return "\n".join(out)


def with_artifact_hash(result: dict[str, Any]) -> dict[str, Any]:
    canonical = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    result["meta"] = {"artifact_hash": hashlib.sha256(canonical).hexdigest()}
    return result


def emit(result: dict[str, Any], emit_mermaid: bool, emit_roadmap: bool = False) -> int:
    if emit_roadmap and result.get("ok"):
        print(render_roadmap_block(result))
    elif emit_mermaid and result.get("ok"):
        print(render_mermaid_flowchart(result))
    else:
        print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #


def verify_and_layer_dag(dag_path: str, min_confidence: float, emit_mermaid: bool) -> int:
    try:
        data = json.loads(Path(dag_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"Cannot read DAG spec: {sanitize_home(str(exc))}"}))
        return 1
    if not isinstance(data, dict) or not isinstance(data.get("nodes", {}), dict):
        print(json.dumps({"ok": False, "error": "DAG spec must be an object with a 'nodes' object"}))
        return 1
    merged = {strip_merged_hint(str(m)) for m in data.get("merged", [])}
    result = compile_and_analyze_dag(merged, data.get("nodes", {}), min_confidence=min_confidence)
    return emit(with_artifact_hash(result), emit_mermaid)


def mutate_edge(repo: str, parent: IssueRef, child: IssueRef, add: bool, errors: list[dict[str, str]]) -> bool:
    """Record or remove 'parent blocks child' on GitHub, across repositories. Returns True on success."""
    parent_db_id = gh_issue_database_id(repo, parent[0], parent[1], errors)
    if parent_db_id is None:
        return False
    child_slug, child_num = child
    if add:
        cmd = ["gh", "api", "-X", "POST", f"repos/{child_slug}/issues/{child_num}/dependencies/blocked_by", "-F", f"issue_id={parent_db_id}"]
    else:
        cmd = ["gh", "api", "-X", "DELETE", f"repos/{child_slug}/issues/{child_num}/dependencies/blocked_by/{parent_db_id}"]
    ok, _, err = run_cmd_checked(cmd, cwd=repo)
    if not ok:
        errors.append({"source": " ".join(cmd[:4]), "error": err or "command failed"})
    return ok


def compile_from_github(repo: str, milestone: str | None, min_confidence: float, emit_mermaid: bool, add_edge: str | None, remove_edge: str | None, reason: str, require_house_format: bool = False, emit_roadmap: bool = False) -> int:
    errors: list[dict[str, str]] = []
    mutation: dict[str, Any] | None = None

    if add_edge or remove_edge:
        if parse_edge_arg(add_edge or remove_edge or "", "home/home") is None:
            print(json.dumps({"ok": False, "error": f"Invalid edge syntax (expected '#parent->#child' or 'owner/repo#parent->owner/repo#child'): {add_edge or remove_edge}"}))
            return 1
        slug = gh_repo_slug(repo, errors)
        if slug is None:
            print(json.dumps({"ok": False, "error": "GitHub mutation failed", "github_errors": errors}, indent=2))
            return 2
        parsed = parse_edge_arg(add_edge or remove_edge or "", slug)
        assert parsed is not None
        parent, child = parsed
        if parent == child:
            print(json.dumps({"ok": False, "error": f"Self-edge rejected: {node_id(child[0], child[1], slug)}"}))
            return 1
        if not mutate_edge(repo, parent, child, add=bool(add_edge), errors=errors):
            print(json.dumps({"ok": False, "error": "GitHub mutation failed", "github_errors": errors}, indent=2))
            return 2
        child_id = node_id(child[0], child[1], slug)
        mutation = {"type": "add_blocked_by" if add_edge else "remove_blocked_by", "parent": node_id(parent[0], parent[1], slug), "child": child_id, "reason": reason, "recorded_in": f"GitHub issue {child_id} dependencies (timeline is the ledger)"}

    source = collect_github_dag(repo, milestone, errors)
    if errors:
        print(json.dumps({"ok": False, "error": "GitHub inventory failed; refusing to compile a partial graph", "github_errors": errors, "mutation": mutation}, indent=2))
        return 2

    result = compile_and_analyze_dag(source["merged"], source["nodes"], min_confidence=min_confidence)
    result["source"] = {
        "kind": "github-native-dependencies",
        "repository": source.get("slug"),
        "milestone_filter": milestone,
        "containers_excluded": source["containers"],
        "external_open_blockers": source["external_open_blockers"],
        "not_planned_parents": source["not_planned_parents"],
        "container_blockers": source.get("container_blockers", []),
    }
    result["label_audit"] = label_audit(source["nodes"], source["merged"])
    if mutation:
        result["mutation"] = mutation

    violations = {nid: meta["house_format_violations"] for nid, meta in source["nodes"].items() if meta.get("house_format_violations") and nid not in source["merged"]}
    result["house_format"] = {
        "standard": "# <Type> heading, ```text execution prompt, sections 1-9, no machine-local paths",
        "nodes_checked": len([n for n in source["nodes"] if n not in source["merged"]]),
        "violating_nodes": len(violations),
        "violations": violations,
        "required": require_house_format,
    }
    if require_house_format and violations and result.get("ok"):
        result["ok"] = False
        result["error"] = f"{len(violations)} open issue(s) do not meet the house card standard"

    if not result.get("ok") and mutation and mutation["type"] == "add_blocked_by":
        # Roll the GitHub write back so a cycle never persists in the truth source.
        rb_errors: list[dict[str, str]] = []
        home = source.get("slug") or ""
        parent, child = parse_edge_arg(add_edge or "", home) or ((home, 0), (home, 0))
        rolled = mutate_edge(repo, parent, child, add=False, errors=rb_errors)
        result["mutation"]["rolled_back"] = rolled
        if rb_errors:
            result["mutation"]["rollback_errors"] = rb_errors

    return emit(with_artifact_hash(result), emit_mermaid, emit_roadmap)


def main() -> int:
    parser = argparse.ArgumentParser(description="Zero-local-state issue DAG compiler, frontier ranker, and inventory for issue-dag.")
    parser.add_argument("--repo", default=".", help="Path inside the git repository (gh resolves the GitHub repo from it)")
    parser.add_argument("--milestone", default=None, help="Optional GitHub milestone title filter")
    parser.add_argument("--from-github", action="store_true", help="Compile the DAG from GitHub issues and native blocked_by dependencies")
    parser.add_argument("--verify-dag", default=None, help="Path to a hand-written DAG JSON specification to verify and layer")
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE, help=f"Minimum confidence for hard edges in --verify-dag specs (default {DEFAULT_MIN_CONFIDENCE})")
    parser.add_argument("--emit-mermaid", action="store_true", help="Output a transitively-reduced Mermaid flowchart TD")
    parser.add_argument("--add-edge", default=None, help="Record '#parent->#child' as a GitHub blocked_by dependency, then recompile (rolls back on cycle). Use 'owner/repo#N' for an issue in another repository.")
    parser.add_argument("--remove-edge", default=None, help="Remove the '#parent->#child' GitHub blocked_by dependency, then recompile. Use 'owner/repo#N' for an issue in another repository.")
    parser.add_argument("--reason", default="issue-dag edge update", help="Rationale echoed in the output for the mutation (GitHub timeline is the ledger)")
    parser.add_argument("--emit-roadmap", action="store_true", help="With --from-github: print the generated ROADMAP.md block (between BEGIN/END markers)")
    parser.add_argument("--require-house-format", action="store_true", help="Fail (exit 1) when any open issue body misses the house card standard")
    args = parser.parse_args()

    if (args.add_edge or args.remove_edge) and not args.from_github:
        parser.error("--add-edge/--remove-edge require --from-github")
    if args.add_edge and args.remove_edge:
        parser.error("--add-edge and --remove-edge are mutually exclusive")
    if args.emit_roadmap and not args.from_github:
        parser.error("--emit-roadmap requires --from-github")
    if args.verify_dag and args.from_github:
        parser.error("--verify-dag and --from-github are mutually exclusive")

    repo = os.path.abspath(args.repo)
    if args.from_github:
        return compile_from_github(repo, args.milestone, args.min_confidence, args.emit_mermaid, args.add_edge, args.remove_edge, args.reason, require_house_format=args.require_house_format, emit_roadmap=args.emit_roadmap)
    if args.verify_dag:
        return verify_and_layer_dag(args.verify_dag, args.min_confidence, args.emit_mermaid)

    errors: list[dict[str, str]] = []
    snapshot = {
        "ok": True,
        "worktrees": collect_worktrees(repo, errors),
        "unmerged_branches": collect_unmerged_branches(repo, errors),
        "github": collect_github_inventory(repo, args.milestone, errors),
        "inventory_errors": errors,
    }
    if errors:
        snapshot["ok"] = False
        print(json.dumps(snapshot, indent=2))
        return 2
    print(json.dumps(snapshot, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
