#!/usr/bin/env python3
"""
taskalisk.py

Taskalisk: zero-local-state DAG compiler for issue frontmatter. Issue frontmatter
(`issue-dag/2`, see docs/frontmatter-model.md) is the single source of truth:
each issue's first fenced `yaml` block declares its kind, its `.blocked_by`
edges, its container `.children`, and the resources it holds. Labels,
milestones, body sections, and GitHub relationships never create edges.
Every issue reference is `owner/repo#N`; a bare `#N` is invalid,
because transferring an issue would silently re-point it. Nothing is
cached or written on disk.

Modes:
  --from-github [--root <ref>] [--emit-mermaid] [--emit-roadmap]
      Read-only. Discovers the closure from the open home issues (or the
      roots) through `.blocked_by` and `.children`, across repositories,
      compiles the transitively-reduced DAG, ranks the Open Frontier, and
      proposes a batch that respects `.holds` and `.meters`.
      Trust flags: --trust <login>, --trust-owner <owner>, --trust-repo
      <owner/repo>, --trust-codeowners (docs/threat-model.md).
  --from-github --add-edge "owner/repo#1080->owner/repo#1052" [--reason "..."]
      Adds the parent to the child's frontmatter `.blocked_by`, then
      recompiles. If the edge creates a cycle the old body is restored and
      the run fails.
  --from-github --remove-edge "owner/repo#1080->owner/repo#1052"
      Removes the parent from the child's `.blocked_by`.
  --from-github --compare-relationships
      Also reports drift between frontmatter edges and GitHub blocked_by
      relationships, which are an optional mirror.
  --verify-dag dag.json [--min-confidence 0.7] [--emit-mermaid]
      Read-only. Compiles a hand-written DAG specification (input, not state).
  --repo <path> [--milestone v21.0.0]
      Read-only. Full-spectrum inventory: worktrees, unmerged branches, open
      PRs, open issues. Exit 2 on any tool failure or possible truncation.

Guarantees:
1. DAG purity: only frontmatter `.blocked_by` entries enter the graph.
2. Fail closed: any `gh`/`git` failure, unparseable JSON, or list result that
   fills its query limit is an error (exit 2), never an empty backlog.
3. Edges come with evidence: each edge cites the frontmatter that declares it.
   Completion comes only from the GitHub issue state.
4. Strict frontmatter: an unknown `.` key, a wrong `.id`, a container used as
   a blocker, or a malformed value fails the run (exit 1).
5. Lexical lock conflicts: `.holds` keys are lexical; a trailing `/` claims a
   subtree, so `docs/` conflicts with `docs/plans/`. A semaphore with unknown
   capacity counts as exclusive.
6. Trust gate (docs/threat-model.md): an issue is a node only when its
   repository is in the trusted scope and its author and every body editor
   are trusted. A linked PR counts only from a same-repository branch by a
   trusted author. Untrusted issues and PRs are listed, never dispatched, and
   contribute nothing to the graph or to rendered output. A failed GraphQL
   trust lookup exits 2; a collaborator check that cannot run marks that
   login untrusted and the run continues with the reason recorded.
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

PARKED_STATUS = "parked"


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
        # author and isCrossRepository feed the PR trust check (C4); without them every PR is untrusted.
        "--json", "number,title,headRefName,isDraft,url,closingIssuesReferences,author,isCrossRepository",
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
ISSUE_REF_RE = re.compile(r"\s*(?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<num>[1-9][0-9]*)\s*")
REPOSITORY_URL_RE = re.compile(r"/repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/?$")


def node_id(slug: str, number: int, home: str = "") -> str:
    """Canonical node id: always 'owner/repo#123'. A bare '#123' is never produced or accepted,
    because a transferred issue would silently re-point a repository-relative reference."""
    return f"{slug}#{number}"


def parse_issue_ref(text: str, home: str = "") -> IssueRef | None:
    """Parse 'owner/repo#123'. A bare '#123' or '123' is invalid."""
    m = ISSUE_REF_RE.fullmatch(text)
    if not m:
        return None
    return (m.group("slug"), int(m.group("num")))


def parse_edge_arg(arg: str, home: str = "") -> tuple[IssueRef, IssueRef] | None:
    """'owner/repo#1080->owner/repo#1052' means the first blocks the second (parent -> child)."""
    parts = arg.split("->")
    if len(parts) != 2:
        return None
    parent, child = parse_issue_ref(parts[0]), parse_issue_ref(parts[1])
    if parent is None or child is None:
        return None
    return parent, child


def slug_from_repository_url(url: str) -> str | None:
    m = REPOSITORY_URL_RE.search(url or "")
    return m.group(1) if m else None


def id_sort_key(nid: str) -> tuple[str, int]:
    """Sort by repository slug, then by number."""
    slug, _, num = nid.rpartition("#")
    return (slug, int(num) if num.isdigit() else 0)


# --------------------------------------------------------------------------- #
# Frontmatter model (issue-dag/2). See docs/frontmatter-model.md.
# --------------------------------------------------------------------------- #

FM_SCHEMA = "issue-dag/2"
FM_RETIRED_SCHEMAS = {"issue-dag/1": "issue-dag/1 allowed repository-relative references; rewrite every reference as owner/repo#N and set .dag: issue-dag/2"}
FM_PREFIX = "."
FM_KEYS = {".dag", ".id", ".kind", ".type", ".blocked_by", ".children", ".size_hours", ".holds", ".meters", ".status"}
FM_KINDS = {"task", "container"}
FM_TYPES = {"feature", "bug", "decision", "research", "investigation", "spike", "task"}
FM_STATUSES = {"active", "parked", "blocked"}
FM_SIZE_WARN_HOURS = 8
FM_BLOCK_RE = re.compile(r"\A\s*```yaml[ \t]*\r?\n(?P<yaml>.*?)\r?\n```[ \t]*(?:\r?\n|\Z)", re.S)
FM_LINE_RE = re.compile(r"(?P<key>\.?[A-Za-z_][A-Za-z0-9_-]*)[ \t]*:[ \t]*(?P<value>.*)")
METER_RE = re.compile(r"(?P<name>[A-Za-z0-9_./-]+)(?:\*(?P<slots>[1-9][0-9]*))?")


def _fm_scalar(text: str) -> Any:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    return text


def parse_frontmatter(body: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Return (fields, problems). fields is None when the body has no frontmatter block.

    The accepted YAML subset is flat: `key: scalar` or `key: [a, b]`. Anything
    else is a problem, so the parser never guesses.
    """
    m = FM_BLOCK_RE.match(body or "")
    if not m:
        return None, []
    fields: dict[str, Any] = {}
    problems: list[str] = []
    for n, raw in enumerate(m.group("yaml").splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        lm = FM_LINE_RE.fullmatch(line)
        if not lm:
            problems.append(f"line {n}: not 'key: value': {line.strip()[:60]}")
            continue
        key, value = lm.group("key"), lm.group("value").strip()
        if key in fields:
            problems.append(f"line {n}: duplicate key {key}")
            continue
        if value.startswith("["):
            if not value.endswith("]"):
                problems.append(f"line {n}: unterminated list for {key}")
                continue
            inner = value[1:-1].strip()
            fields[key] = [str(_fm_scalar(item)) for item in inner.split(",")] if inner else []
        else:
            fields[key] = _fm_scalar(value)
    return fields, problems


def validate_frontmatter(fields: dict[str, Any], self_ref: IssueRef) -> tuple[dict[str, Any], list[str], list[str]]:
    """Return (record, violations, warnings). References resolve relative to self_ref's repository."""
    v: list[str] = []
    w: list[str] = []
    slug = self_ref[0]
    for key in sorted(k for k in fields if k.startswith(FM_PREFIX) and k not in FM_KEYS):
        v.append(f"unknown key {key}")
    dag = fields.get(".dag")
    if dag in FM_RETIRED_SCHEMAS:
        v.append(f".dag {dag} is retired: {FM_RETIRED_SCHEMAS[dag]}")
    elif dag != FM_SCHEMA:
        v.append(f".dag must be {FM_SCHEMA}")
    own = parse_issue_ref(str(fields.get(".id", "")))
    if own is None:
        v.append(f".id {fields.get('.id')!r} must be owner/repo#N")
    elif own != self_ref:
        v.append(f".id {fields.get('.id')} does not name this issue ({node_id(*self_ref)}); was it transferred or copied?")
    kind = fields.get(".kind")
    if kind not in FM_KINDS:
        v.append(".kind must be task or container")

    def refs(key: str) -> list[IssueRef]:
        raw = fields.get(key, [])
        if not isinstance(raw, list):
            v.append(f"{key} must be a list")
            return []
        out: list[IssueRef] = []
        for item in raw:
            r = parse_issue_ref(item)
            if r is None:
                v.append(f"{key}: invalid reference {item!r} (use owner/repo#N; bare numbers are not allowed)")
            elif r == self_ref:
                v.append(f"{key}: self reference")
            else:
                out.append(r)
        return out

    record: dict[str, Any] = {"kind": kind, "type": fields.get(".type"), "blocked_by": [], "children": [], "holds": [], "meters": [], "status": fields.get(".status"), "size_hours": fields.get(".size_hours")}
    if kind == "task":
        if fields.get(".type") not in FM_TYPES:
            v.append(".type must be one of " + ", ".join(sorted(FM_TYPES)))
        if ".blocked_by" not in fields:
            v.append("a task needs .blocked_by (use [] for none)")
        if ".children" in fields:
            v.append("a task must not have .children")
        record["blocked_by"] = refs(".blocked_by")
    elif kind == "container":
        if ".children" not in fields:
            v.append("a container needs .children")
        if fields.get(".blocked_by"):
            v.append("a container must not have .blocked_by")
        record["children"] = refs(".children")
    holds = fields.get(".holds", [])
    if not isinstance(holds, list) or not all(isinstance(h, str) and h for h in holds):
        v.append(".holds must be a list of git-locks keys")
    else:
        record["holds"] = sorted(set(holds))
    meters = fields.get(".meters", [])
    if not isinstance(meters, list):
        v.append(".meters must be a list")
    else:
        for item in meters:
            mm = METER_RE.fullmatch(item)
            if not mm:
                v.append(f".meters: invalid entry {item!r} (use name or name*N)")
            else:
                record["meters"].append({"name": mm.group("name"), "slots": int(mm.group("slots") or 1)})
    if record["status"] is not None and record["status"] not in FM_STATUSES:
        v.append(".status must be active, parked, or blocked")
    size = record["size_hours"]
    if size is not None:
        if not isinstance(size, int) or size <= 0:
            v.append(".size_hours must be a positive integer")
        elif size > FM_SIZE_WARN_HOURS:
            w.append(f".size_hours {size} is above {FM_SIZE_WARN_HOURS}; the card is probably not atomic")
    return record, v, w


def format_ref_relative(ref: IssueRef, base_slug: str = "") -> str:
    """Always the qualified form; the name is kept for call sites."""
    return f"{ref[0]}#{ref[1]}"


def rewrite_blocked_by(body: str, refs: list[IssueRef], base_slug: str) -> str | None:
    """Replace only the .blocked_by line of the frontmatter block. None when it cannot."""
    m = FM_BLOCK_RE.match(body or "")
    if not m:
        return None
    block = m.group("yaml")
    new_line = ".blocked_by: [" + ", ".join(format_ref_relative(r, base_slug) for r in refs) + "]"
    lines = block.splitlines()
    hits = [i for i, line in enumerate(lines) if re.match(r"\.blocked_by[ \t]*:", line)]
    if len(hits) != 1:
        return None
    lines[hits[0]] = new_line
    start, end = m.span("yaml")
    return body[:start] + "\n".join(lines) + body[end:]


def gh_get_issue(repo: str, ref: IssueRef, errors: list[dict[str, str]]) -> dict[str, Any] | None:
    ok, raw, err = run_cmd_checked(["gh", "api", f"repos/{ref[0]}/issues/{ref[1]}"], cwd=repo)
    if not ok:
        errors.append({"source": f"gh api repos/{ref[0]}/issues/{ref[1]}", "error": err or "command failed"})
        return None
    obj = parse_json(raw, f"gh api repos/{ref[0]}/issues/{ref[1]}", errors)
    return obj if isinstance(obj, dict) else None


def gh_patch_body(repo: str, ref: IssueRef, body: str, errors: list[dict[str, str]]) -> bool:
    try:
        proc = subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{ref[0]}/issues/{ref[1]}", "--input", "-"],
                              cwd=repo, input=json.dumps({"body": body}), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    except (FileNotFoundError, PermissionError) as exc:
        errors.append({"source": f"gh api PATCH repos/{ref[0]}/issues/{ref[1]}", "error": sanitize_home(str(exc))})
        return False
    if proc.returncode != 0:
        errors.append({"source": f"gh api PATCH repos/{ref[0]}/issues/{ref[1]}", "error": sanitize_home(proc.stderr.strip()) or "command failed"})
        return False
    return True


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


# --------------------------------------------------------------------------- #
# Trust (docs/threat-model.md, controls C1-C4 and C18)
# --------------------------------------------------------------------------- #

# OWNER is the only association that implies write access by itself. MEMBER and
# COLLABORATOR include read- and triage-level people, so they go through the
# permission check like everyone else.
TRUSTED_ASSOCIATIONS = {"OWNER"}
TRUSTED_PERMISSIONS = {"admin", "maintain", "write"}
CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
UNTRUSTED_TITLE = "(untrusted issue)"
OWNER_RE = re.compile(r"[A-Za-z0-9_.-]+")
SLUG_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
# Author, association and the login of every body edit (the first edit is the creation).
TRUST_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!,$after:String){"
    "repository(owner:$owner,name:$name){issue(number:$number){"
    "author{login} authorAssociation "
    "userContentEdits(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{editor{login}}}}}}"
)


def parse_codeowners(text: str) -> tuple[set[str], list[str]]:
    """Return (logins, teams) named as owners. Email owners are ignored."""
    logins: set[str] = set()
    teams: list[str] = []
    for raw in text.splitlines():
        tokens = raw.split("#", 1)[0].split()
        for token in tokens[1:]:
            if not token.startswith("@"):
                continue
            name = token[1:]
            if "/" in name:
                if name not in teams:
                    teams.append(name)
            elif name:
                logins.add(name)
    return logins, teams


def gh_issue_trust_info(repo: str, ref: IssueRef, errors: list[dict[str, str]]) -> dict[str, Any] | None:
    """Author, author association and every body editor of an issue, from GitHub's edit history."""
    owner, name = ref[0].split("/", 1)
    source = f"gh api graphql (trust of {node_id(*ref)})"
    editors: list[str | None] = []
    after: str | None = None
    while True:
        cmd = ["gh", "api", "graphql", "-f", f"query={TRUST_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={ref[1]}"]
        if after:
            cmd += ["-f", f"after={after}"]
        ok, raw, err = run_cmd_checked(cmd, cwd=repo)
        if not ok:
            errors.append({"source": source, "error": err or "command failed"})
            return None
        data = parse_json(raw, source, errors)
        issue = (((data or {}).get("data") or {}).get("repository") or {}).get("issue") if isinstance(data, dict) else None
        if not isinstance(issue, dict):
            errors.append({"source": source, "error": "GraphQL response has no issue"})
            return None
        edits = issue.get("userContentEdits") or {}
        for node in edits.get("nodes") or []:
            editors.append(((node or {}).get("editor") or {}).get("login"))
        page = edits.get("pageInfo") or {}
        if page.get("hasNextPage") and page.get("endCursor"):
            after = str(page["endCursor"])
            continue
        return {"author": (issue.get("author") or {}).get("login"), "association": issue.get("authorAssociation"), "editors": editors}


class TrustPolicy:
    """Who may be a node. Association counts only inside the repository scope (C2)."""

    def __init__(self, repo: str, home_slug: str, owners: list[str], repos: list[str], logins: list[str], codeowners: bool, errors: list[dict[str, str]]):
        # GitHub owner, repository and login names are case-insensitive; compare them folded.
        self.repo = repo
        self.owners = {home_slug.split("/", 1)[0].lower(), *(o.lower() for o in owners)}
        self.repos = {r.lower() for r in repos}
        self.logins = {l.lower() for l in logins}
        self.codeowners = codeowners
        self.errors = errors
        self._repo_logins: dict[str, set[str]] = defaultdict(set)
        self._teams: dict[str, list[str]] = {}
        self._codeowners_loaded: set[str] = set()
        self._collaborator_cache: dict[tuple[str, str], tuple[bool, str]] = {}

    def in_scope(self, slug: str) -> bool:
        return slug.lower() in self.repos or slug.split("/", 1)[0].lower() in self.owners

    def describe(self) -> dict[str, Any]:
        return {
            "owners": sorted(self.owners),
            "repos": sorted(self.repos),
            "logins": sorted(self.logins),
            "codeowners": {slug: sorted(v) for slug, v in sorted(self._repo_logins.items())} if self.codeowners else None,
            "codeowners_teams_not_expanded": dict(sorted(self._teams.items())),
        }

    def login_trusted(self, slug: str, login: str | None, association: str | None = None) -> tuple[bool, str]:
        if not login:
            return False, "no login (deleted user or bot)"
        login_key = login.lower()
        if login_key in self.logins:
            return True, "allowlisted"
        if not self.in_scope(slug):
            return False, f"{slug} is outside the trusted repositories"
        self._load_codeowners(slug)
        if login_key in self._repo_logins.get(slug.lower(), set()):
            return True, "CODEOWNERS"
        if association in TRUSTED_ASSOCIATIONS:
            return True, f"association {association}"
        return self._collaborator(slug, login)

    def issue_trust(self, slug: str, info: dict[str, Any]) -> tuple[bool, list[str]]:
        """(trusted, reasons). The author and every editor must be trusted."""
        reasons: list[str] = []
        author = info.get("author")
        ok, why = self.login_trusted(slug, author, info.get("association"))
        if not ok:
            reasons.append(f"author {author or '(none)'}: {why}")
        seen: set[str | None] = {author}
        for editor in info.get("editors") or []:
            if editor in seen:
                continue
            seen.add(editor)
            ok_e, why_e = self.login_trusted(slug, editor)
            if not ok_e:
                reasons.append(f"editor {editor or '(none)'}: {why_e}")
        return not reasons, reasons

    def _collaborator(self, slug: str, login: str) -> tuple[bool, str]:
        """Trusted only with write, maintain or admin permission; read and triage are not enough to edit others' issues safely."""
        key = (slug.lower(), login.lower())
        if key not in self._collaborator_cache:
            ok, raw, err = run_cmd_checked(["gh", "api", f"repos/{slug}/collaborators/{login}/permission", "--jq", ".permission"], cwd=self.repo)
            if ok and raw in TRUSTED_PERMISSIONS:
                self._collaborator_cache[key] = (True, f"permission {raw}")
            elif ok:
                self._collaborator_cache[key] = (False, f"permission {raw or 'none'} on {slug} is below write")
            elif "HTTP 404" in err:
                self._collaborator_cache[key] = (False, f"not a collaborator of {slug}")
            else:
                self._collaborator_cache[key] = (False, f"collaborator check failed ({err or 'command failed'})")
        return self._collaborator_cache[key]

    def _load_codeowners(self, slug: str) -> None:
        """Read CODEOWNERS from the default branch of a scope repository (C18)."""
        slug_key = slug.lower()
        if not self.codeowners or slug_key in self._codeowners_loaded:
            return
        self._codeowners_loaded.add(slug_key)
        for path in CODEOWNERS_PATHS:
            source = f"gh api repos/{slug}/contents/{path}"
            ok, raw, err = run_cmd_checked(["gh", "api", f"repos/{slug}/contents/{path}", "-H", "Accept: application/vnd.github.raw+json"], cwd=self.repo)
            if ok:
                logins, teams = parse_codeowners(raw)
                self._repo_logins[slug_key] |= {l.lower() for l in logins}
                if teams:
                    self._teams[slug_key] = teams
                return
            if "HTTP 404" not in err:
                self.errors.append({"source": source, "error": err or "command failed"})
                return


def collect_frontmatter_dag(repo: str, roots: list[str], errors: list[dict[str, str]], trust: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build (merged, nodes) from issue frontmatter, across repositories."""
    empty: dict[str, Any] = {"merged": set(), "nodes": {}, "containers": [], "slug": None}
    slug = gh_repo_slug(repo, errors)
    if slug is None:
        return empty
    trust = trust or {}
    policy = TrustPolicy(repo, slug, trust.get("owners", []), trust.get("repos", []), trust.get("logins", []), bool(trust.get("codeowners")), errors)
    prs = gh_list_open_prs(repo, errors)
    branches = list_branches(repo, errors)
    fetched: dict[IssueRef, dict[str, Any]] = {}
    queue: deque[IssueRef] = deque()
    seeds: set[IssueRef] = set()
    if roots:
        for text in roots:
            r = parse_issue_ref(text)
            if r is None:
                errors.append({"source": "--root", "error": f"invalid reference {text!r} (use owner/repo#N)"})
            elif not policy.in_scope(r[0]):
                errors.append({"source": "--root", "error": f"{node_id(*r)} is outside the trusted repositories (add --trust-owner or --trust-repo)"})
            else:
                seeds.add(r)
    else:
        for iss in gh_list_open_issues(repo, None, errors):
            r = (slug, int(iss["number"]))
            fetched[r] = {"title": iss.get("title", ""), "state": "open", "state_reason": None, "body": iss.get("body") or "", "html_url": iss.get("url")}
            seeds.add(r)
    if errors:
        return empty
    queue.extend(sorted(seeds))

    # A PR links a task only from a same-repository branch by a trusted author (C4).
    prs_by_issue: dict[IssueRef, list[dict[str, Any]]] = defaultdict(list)
    untrusted_prs: list[dict[str, Any]] = []
    for pr in prs:
        closes: list[IssueRef] = []
        for ref in pr.get("closingIssuesReferences", []) or []:
            if isinstance(ref, dict) and "number" in ref:
                repo_info = ref.get("repository") or {}
                owner = (repo_info.get("owner") or {}).get("login")
                ref_slug = f"{owner}/{repo_info['name']}" if owner and repo_info.get("name") else slug
                closes.append((ref_slug, int(ref["number"])))
        if not closes:
            continue
        author = (pr.get("author") or {}).get("login")
        cross = pr.get("isCrossRepository")
        ok, why = (False, "head is not a branch of this repository") if cross is not False else policy.login_trusted(slug, author)
        if not ok:
            untrusted_prs.append({"number": pr.get("number"), "url": pr.get("url"), "author": author, "cross_repository": cross, "closes": [node_id(*c) for c in closes], "reason": why})
            continue
        for c in closes:
            prs_by_issue[c].append({"number": pr["number"], "isDraft": pr.get("isDraft", False), "url": pr.get("url")})

    seen: set[IssueRef] = set()
    referenced_by: dict[IssueRef, list[str]] = defaultdict(list)
    records: dict[IssueRef, dict[str, Any]] = {}
    violations: dict[str, list[str]] = {}
    warnings: dict[str, list[str]] = {}
    unmodeled_seeds: list[dict[str, Any]] = []
    untrusted: list[dict[str, Any]] = []
    opaque: list[dict[str, Any]] = []
    containers: list[dict[str, Any]] = []
    not_planned: list[dict[str, Any]] = []
    while queue:
        ref = queue.popleft()
        if ref in seen:
            continue
        seen.add(ref)
        nid = node_id(ref[0], ref[1], slug)
        if not policy.in_scope(ref[0]):
            # Never fetch outside the scope: the attacker is OWNER of their own repository (C2).
            hint = f"add --trust-owner {ref[0].split('/', 1)[0]} or --trust-repo {ref[0]}"
            for who in referenced_by[ref] or [nid]:
                violations.setdefault(who, []).append(f"reference {nid} is outside the trusted repositories; {hint}")
            continue
        if ref not in fetched:
            obj = gh_get_issue(repo, ref, errors)
            if obj is None:
                break
            if obj.get("pull_request"):
                violations[nid] = ["references a pull request, not an issue"]
                continue
            actual_slug = slug_from_repository_url(str(obj.get("repository_url") or ""))
            actual = (actual_slug, int(obj.get("number", 0))) if actual_slug else None
            if actual is None:
                errors.append({"source": f"gh api repos/{ref[0]}/issues/{ref[1]}", "error": "issue has no parseable repository_url"})
                break
            if actual != ref:
                moved = node_id(*actual)
                for who in referenced_by[ref] or [nid]:
                    violations.setdefault(who, []).append(f"reference {nid} moved to {moved} (transferred); update the frontmatter")
                continue
            fetched[ref] = {"title": obj.get("title", ""), "state": str(obj.get("state", "")).lower(), "state_reason": obj.get("state_reason"), "body": obj.get("body") or "", "html_url": obj.get("html_url")}
        meta = fetched[ref]
        info = gh_issue_trust_info(repo, ref, errors)
        if info is None:
            break
        trusted, reasons = policy.issue_trust(ref[0], info)
        if not trusted:
            # No title: nothing an untrusted author wrote reaches any output (C3).
            untrusted.append({"id": nid, "url": meta["html_url"], "state": meta["state"], "author": info.get("author"), "reasons": reasons, "referenced_by": referenced_by[ref]})
            # Always an opaque record: a trusted issue that references it must stay blocked (C3).
            # Unreferenced untrusted seeds are dropped after discovery, below.
            records[ref] = {"kind": "opaque", "untrusted": True, "blocked_by": [], "children": [], "holds": [], "meters": [], "status": "blocked", "size_hours": None, "type": None}
            continue
        fields, problems = parse_frontmatter(meta["body"])
        if fields is None:
            if ref in seeds and not roots:
                unmodeled_seeds.append({"id": nid, "title": meta["title"], "url": meta["html_url"]})
            else:
                opaque.append({"id": nid, "title": meta["title"], "state": meta["state"], "referenced_by": referenced_by[ref]})
                records[ref] = {"kind": "opaque", "blocked_by": [], "children": [], "holds": [], "meters": [], "status": "blocked", "size_hours": None, "type": None}
            continue
        record, v, w = validate_frontmatter(fields, ref)
        v = problems + v
        if v:
            violations[nid] = v
        if w:
            warnings[nid] = w
        records[ref] = record
        for child in record["children"]:
            referenced_by[child].append(nid)
            queue.append(child)
        for blk in record["blocked_by"]:
            referenced_by[blk].append(nid)
            queue.append(blk)
    if errors:
        return empty
    # An untrusted seed (home issue or --root) that no trusted issue references is listed only, never a node.
    for ref in [r for r, rec in records.items() if rec.get("untrusted") and r in seeds and not referenced_by.get(r)]:
        del records[ref]

    merged: set[str] = set()
    nodes: dict[str, dict[str, Any]] = {}
    for ref, rec in records.items():
        nid = node_id(ref[0], ref[1], slug)
        meta = fetched[ref]
        if rec["kind"] == "container":
            containers.append({"id": nid, "number": ref[1], "title": meta["title"], "children": [node_id(c[0], c[1], slug) for c in rec["children"]]})
            continue
        if meta["state"] == "closed":
            merged.add(nid)
            continue
        depends_on = []
        for blk in rec["blocked_by"]:
            bid = node_id(blk[0], blk[1], slug)
            brec = records.get(blk)
            if brec and brec["kind"] == "container":
                violations.setdefault(nid, []).append(f".blocked_by names container {bid}")
                continue
            bmeta = fetched.get(blk, {})
            evidence = f"frontmatter: {nid} .blocked_by {bid}"
            if bmeta.get("state") == "closed" and str(bmeta.get("state_reason") or "") == "not_planned":
                # A closed untrusted blocker still contributes no title (C3).
                btitle = UNTRUSTED_TITLE if (brec or {}).get("untrusted") else bmeta.get("title", "")
                not_planned.append({"parent": bid, "child": nid, "title": btitle})
            depends_on.append({"from": bid, "type": "frontmatter", "isHard": True, "confidence": 1.0, "evidence": evidence})
        untrusted_node = bool(rec.get("untrusted"))
        linked = prs_by_issue.get(ref, []) if ref[0] == slug and not untrusted_node else []
        status = rec["status"] or "open"
        if status == "active" or linked:
            status = "in-progress"
        elif status == "parked":
            status = PARKED_STATUS
        nodes[nid] = {
            "title": UNTRUSTED_TITLE if untrusted_node else meta["title"], "type": rec["type"] or ("opaque" if rec["kind"] == "opaque" else "task"),
            "workstream": rec["type"] or "unassigned", "status": status, "depends_on": depends_on,
            "holds": rec["holds"], "meters": rec["meters"], "size_hours": rec["size_hours"],
            "linked_open_prs": linked, "recoverable_branches": branches_for_issue(ref[1], branches) if ref[0] == slug else [],
            "url": meta["html_url"], "opaque": rec["kind"] == "opaque", "untrusted": untrusted_node,
        }
    return {"merged": merged, "nodes": nodes, "containers": containers, "slug": slug,
            "violations": violations, "warnings": warnings, "unmodeled_open_issues": unmodeled_seeds,
            "opaque_nodes": opaque, "not_planned_parents": not_planned, "records": records, "fetched": fetched,
            "untrusted_issues": untrusted, "untrusted_linked_prs": untrusted_prs, "trust": policy.describe()}


def compare_relationships(repo: str, source: dict[str, Any], errors: list[dict[str, str]]) -> dict[str, Any]:
    """Drift between frontmatter edges and GitHub blocked_by relationships (a mirror)."""
    slug = source["slug"]
    only_fm: list[str] = []
    only_gh: list[str] = []
    for ref, rec in source["records"].items():
        if rec["kind"] != "task" or source["fetched"][ref]["state"] == "closed":
            continue
        nid = node_id(ref[0], ref[1], slug)
        gh_set = set()
        for blk in gh_blocked_by(repo, ref[0], ref[1], errors):
            b_slug = slug_from_repository_url(str(blk.get("repository_url") or ""))
            if b_slug:
                gh_set.add((b_slug, int(blk["number"])))
        fm_set = set(rec["blocked_by"])
        only_fm += [f"{node_id(b[0], b[1], slug)} -> {nid}" for b in sorted(fm_set - gh_set)]
        only_gh += [f"{node_id(b[0], b[1], slug)} -> {nid}" for b in sorted(gh_set - fm_set)]
    return {"only_in_frontmatter": only_fm, "only_in_github": only_gh, "in_sync": not only_fm and not only_gh}


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


def compile_and_analyze_dag(merged: set[str], nodes: dict[str, dict[str, Any]], min_confidence: float = DEFAULT_MIN_CONFIDENCE, capacities: dict[str, int] | None = None) -> dict[str, Any]:
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
        holds = meta.get("holds", meta.get("resources", [])) or []
        meters = meta.get("meters", []) or []
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
                "completed_parents": sorted(completed_parents[nid]),
                "open_parents": sorted(reduced_parents[nid]),
                "directly_unlocks": sorted(reduced_children[nid]),
                "transitive_unblocks_count": len(descendants[nid]),
                "critical_path_remaining_depth": remaining[nid],
                "priority_score": score,
                "holds": sorted(set(holds)),
                "meters": meters,
                "opaque": bool(meta.get("opaque")),
                "untrusted": bool(meta.get("untrusted")),
                "size_hours": meta.get("size_hours"),
            }
        )
    for lvl in waves:
        waves[lvl].sort(key=lambda item: (-item["priority_score"], item["id"]))

    frontier = waves.get(0, [])
    caps = dict(capacities or {})
    unknown_capacity: set[str] = set()
    held: set[str] = set()
    used: dict[str, int] = defaultdict(int)
    batch: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for cand in frontier:
        if cand["status"] == BLOCKED_STATUS or cand.get("opaque"):
            continue  # hand-set block or unmodeled issue: never dispatched
        req = set(cand["holds"])
        need: dict[str, int] = defaultdict(int)
        for meter in cand["meters"]:
            need[meter["name"]] += int(meter["slots"])
        for name in need:
            if name not in caps:
                unknown_capacity.add(name)
        over = [n for n, k in need.items() if used[n] + k > caps.get(n, 1)]
        if any_lock_conflict(req, held) or over:
            skipped.append({"id": cand["id"], "reason": "holds conflict" if any_lock_conflict(req, held) else f"semaphore full: {', '.join(sorted(over))}"})
            continue
        held.update(req)
        for n, k in need.items():
            used[n] += k
        batch.append({"id": cand["id"], "title": cand["title"], "url": cand.get("url"), "workstream": cand["workstream"], "priority_score": cand["priority_score"], "holds": sorted(req), "meters": cand["meters"]})

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
        "batch_skipped": skipped,
        "semaphores_with_unknown_capacity_treated_as_1": sorted(unknown_capacity),
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


ROADMAP_BEGIN = "<!-- BEGIN GENERATED ISSUE DAG (taskalisk --emit-roadmap; do not edit by hand) -->"
ROADMAP_END = "<!-- END GENERATED ISSUE DAG -->"


def _issue_link(nid: str, url: str | None) -> str:
    return f"[{nid}]({url})" if url else nid


def _resources_cell(holds: list[str], meters: list[dict[str, Any]], empty: str) -> str:
    cells = [f"`{k}`" for k in holds] + ["`" + str(m["name"]) + "*" + str(m["slots"]) + "`" for m in meters]
    return ", ".join(cells) or empty


def _md_cell(text: str) -> str:
    """Issue text in a rendered table cell: no pipes, no HTML, no line breaks (C5)."""
    return str(text).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;").replace("\n", " ")


def render_roadmap_block(result: dict[str, Any]) -> str:
    """Render the computed ROADMAP sections. Pure function of the compiled DAG."""
    m = result["metrics"]
    src = result.get("source", {})
    waves: dict[str, list[dict[str, Any]]] = result["waves"]
    by_id = {n["id"]: n for items in waves.values() for n in items}
    out: list[str] = [ROADMAP_BEGIN, ""]
    out += [
        f"Compiled from issue frontmatter (`{src.get('schema', '')}`), home `{src.get('repository', '')}`, roots `{', '.join(src.get('roots') or []) or 'all open home issues'}`. "
        f"Artifact hash `{result.get('meta', {}).get('artifact_hash', '')[:16]}`. "
        "Regenerate with `taskalisk.py --from-github [--root <ref>] --emit-roadmap`.",
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
        f"| Containers excluded | {', '.join(c['id'] for c in src.get('containers_excluded', [])) or 'none'} |",
        "",
        "## Ranked Open Frontier (Wave 0)",
        "",
        "| Rank | Score | Issue | Title | Status | Unblocks | Depth | Resources | Directly unlocks |",
        "| ---: | ---: | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for i, n in enumerate(result.get("open_frontier_ranked", []), 1):
        out.append(
            f"| {i} | {n['priority_score']} | {_issue_link(n['id'], n.get('url'))} | {_md_cell(n['title'])} | {n['status']} | "
            f"{n['transitive_unblocks_count']} | {n['critical_path_remaining_depth']} | {_resources_cell(n['holds'], n['meters'], '—')} | "
            f"{', '.join(n['directly_unlocks']) or '—'} |"
        )
    out += ["", "### Conflict-Free git-locks Batch", ""]
    for b in result.get("conflict_free_frontier_batch", []):
        out.append(f"- {_issue_link(b['id'], b.get('url'))} {_md_cell(b['title'])} — {_resources_cell(b['holds'], b['meters'], 'no resources')}")
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


def mutate_edge(repo: str, home: str, parent: IssueRef, child: IssueRef, add: bool, errors: list[dict[str, str]], policy: TrustPolicy) -> dict[str, Any] | None:
    """Edit the child's frontmatter .blocked_by. Returns {"child": ref, "old_body": str} or None."""
    for ref in (parent, child):
        if not policy.in_scope(ref[0]):
            errors.append({"source": f"edge {node_id(*parent)}->{node_id(*child)}", "error": f"{node_id(*ref)} is outside the trusted repositories"})
            return None
    obj = gh_get_issue(repo, child, errors)
    if obj is None:
        return None
    info = gh_issue_trust_info(repo, child, errors)
    if info is None:
        return None
    trusted, reasons = policy.issue_trust(child[0], info)
    if errors:
        # A trust lookup that recorded an error (for example a failed CODEOWNERS fetch) never permits a write.
        return None
    if not trusted:
        # Never write into a stranger's issue, even with the permission to do so (C3).
        errors.append({"source": f"frontmatter of {node_id(child[0], child[1], home)}", "error": "child is untrusted: " + "; ".join(reasons)})
        return None
    body = obj.get("body") or ""
    fields, problems = parse_frontmatter(body)
    if fields is None or problems:
        errors.append({"source": f"frontmatter of {node_id(child[0], child[1], home)}", "error": "missing or unparseable frontmatter"})
        return None
    record, violations, _ = validate_frontmatter(fields, child)
    if violations or record["kind"] != "task":
        errors.append({"source": f"frontmatter of {node_id(child[0], child[1], home)}", "error": "invalid task frontmatter: " + "; ".join(violations or ["not a task"])})
        return None
    refs = list(record["blocked_by"])
    if add and parent not in refs:
        refs.append(parent)
    if not add:
        refs = [r for r in refs if r != parent]
    new_body = rewrite_blocked_by(body, refs, child[0])
    if new_body is None:
        errors.append({"source": f"frontmatter of {node_id(child[0], child[1], home)}", "error": "cannot rewrite .blocked_by"})
        return None
    if new_body != body and not gh_patch_body(repo, child, new_body, errors):
        return None
    return {"child": child, "old_body": body, "changed": new_body != body}


def compile_from_github(repo: str, roots: list[str], min_confidence: float, emit_mermaid: bool, add_edge: str | None, remove_edge: str | None, reason: str, emit_roadmap: bool = False, capacities: dict[str, int] | None = None, compare: bool = False, trust: dict[str, Any] | None = None) -> int:
    errors: list[dict[str, str]] = []
    mutation: dict[str, Any] | None = None
    undo: dict[str, Any] | None = None
    trust = trust or {}

    if add_edge or remove_edge:
        if parse_edge_arg(add_edge or remove_edge or "") is None:
            print(json.dumps({"ok": False, "error": f"Invalid edge syntax (expected 'owner/repo#parent->owner/repo#child'; bare numbers are not allowed): {add_edge or remove_edge}"}))
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
        policy = TrustPolicy(repo, slug, trust.get("owners", []), trust.get("repos", []), trust.get("logins", []), bool(trust.get("codeowners")), errors)
        undo = mutate_edge(repo, slug, parent, child, add=bool(add_edge), errors=errors, policy=policy)
        if undo is None:
            print(json.dumps({"ok": False, "error": "Frontmatter edit failed", "github_errors": errors}, indent=2))
            return 2 if any(e["source"].startswith("gh ") for e in errors) else 1
        child_id = node_id(child[0], child[1], slug)
        mutation = {"type": "add_blocked_by" if add_edge else "remove_blocked_by", "parent": node_id(parent[0], parent[1], slug), "child": child_id, "changed": undo["changed"], "reason": reason, "recorded_in": f"frontmatter of {child_id} (the issue edit history is the ledger)"}

    source = collect_frontmatter_dag(repo, roots, errors, trust)
    if errors:
        print(json.dumps({"ok": False, "error": "GitHub inventory failed; refusing to compile a partial graph", "github_errors": errors, "mutation": mutation}, indent=2))
        return 2

    result = compile_and_analyze_dag(source["merged"], source["nodes"], min_confidence=min_confidence, capacities=capacities)
    result["source"] = {
        "kind": "issue-frontmatter",
        "schema": FM_SCHEMA,
        "repository": source.get("slug"),
        "roots": roots,
        "trust": source["trust"],
        "containers_excluded": [{k: c[k] for k in ("id", "number", "title")} for c in source["containers"]],
        "unmodeled_open_issues": source["unmodeled_open_issues"],
        "untrusted_issues": source["untrusted_issues"],
        "untrusted_linked_prs": source["untrusted_linked_prs"],
        "opaque_nodes": source["opaque_nodes"],
        "not_planned_parents": source["not_planned_parents"],
    }
    result["frontmatter"] = {"violating_issues": len(source["violations"]), "violations": source["violations"], "warnings": source["warnings"]}
    if source["violations"] and result.get("ok"):
        result["ok"] = False
        result["error"] = f"{len(source['violations'])} issue(s) have invalid frontmatter"
    if compare:
        rel_errors: list[dict[str, str]] = []
        result["relationship_drift"] = compare_relationships(repo, source, rel_errors)
        if rel_errors:
            result["relationship_drift"]["errors"] = rel_errors
    if mutation:
        result["mutation"] = mutation

    if not result.get("ok") and mutation and mutation["type"] == "add_blocked_by" and undo and undo["changed"]:
        # Restore the child's body so a cycle never persists in the truth source.
        rb_errors: list[dict[str, str]] = []
        result["mutation"]["rolled_back"] = gh_patch_body(repo, undo["child"], undo["old_body"], rb_errors)
        if rb_errors:
            result["mutation"]["rollback_errors"] = rb_errors

    return emit(with_artifact_hash(result), emit_mermaid, emit_roadmap)


def parse_capacities(items: list[str]) -> dict[str, int] | None:
    caps: dict[str, int] = {}
    for item in items:
        name, _, num = item.partition("=")
        if not name or not num.isdigit() or int(num) < 1:
            return None
        caps[name] = int(num)
    return caps


def main() -> int:
    parser = argparse.ArgumentParser(description="Taskalisk: zero-local-state issue DAG compiler, frontier ranker, and inventory.")
    parser.add_argument("--repo", default=".", help="Path inside the git repository (gh resolves the GitHub repo from it)")
    parser.add_argument("--milestone", default=None, help="Inventory mode only: optional GitHub milestone title filter")
    parser.add_argument("--root", action="append", default=[], help="With --from-github: start discovery at this issue, as owner/repo#N (repeatable); default is every open home issue")
    parser.add_argument("--sem-capacity", action="append", default=[], help="Semaphore capacity as name=N (repeatable); unknown semaphores count as 1")
    parser.add_argument("--compare-relationships", action="store_true", help="With --from-github: report drift between frontmatter edges and GitHub blocked_by relationships")
    parser.add_argument("--from-github", action="store_true", help="Compile the DAG from issue frontmatter (issue-dag/2), across repositories")
    parser.add_argument("--verify-dag", default=None, help="Path to a hand-written DAG JSON specification to verify and layer")
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE, help=f"Minimum confidence for hard edges in --verify-dag specs (default {DEFAULT_MIN_CONFIDENCE})")
    parser.add_argument("--emit-mermaid", action="store_true", help="Output a transitively-reduced Mermaid flowchart TD")
    parser.add_argument("--add-edge", default=None, help="Add 'owner/repo#parent->owner/repo#child' to the child's frontmatter .blocked_by, then recompile (rolls back on cycle).")
    parser.add_argument("--remove-edge", default=None, help="Remove 'owner/repo#parent->owner/repo#child' from the child's frontmatter .blocked_by, then recompile.")
    parser.add_argument("--reason", default="taskalisk edge update", help="Rationale echoed in the output for the mutation (GitHub timeline is the ledger)")
    parser.add_argument("--emit-roadmap", action="store_true", help="With --from-github: print the generated ROADMAP.md block (between BEGIN/END markers)")
    parser.add_argument("--trust", action="append", default=[], metavar="LOGIN", help="With --from-github: a login trusted as author or editor everywhere (repeatable)")
    parser.add_argument("--trust-owner", action="append", default=[], metavar="OWNER", help="With --from-github: add every repository of this owner to the trusted scope (repeatable; the home owner is always in scope)")
    parser.add_argument("--trust-repo", action="append", default=[], metavar="OWNER/REPO", help="With --from-github: add one repository to the trusted scope (repeatable)")
    parser.add_argument("--trust-codeowners", action="store_true", help="With --from-github: trust the logins named in each scope repository's CODEOWNERS on its default branch")
    args = parser.parse_args()

    if (args.add_edge or args.remove_edge) and not args.from_github:
        parser.error("--add-edge/--remove-edge require --from-github")
    if args.add_edge and args.remove_edge:
        parser.error("--add-edge and --remove-edge are mutually exclusive")
    if args.emit_roadmap and not args.from_github:
        parser.error("--emit-roadmap requires --from-github")
    if args.verify_dag and args.from_github:
        parser.error("--verify-dag and --from-github are mutually exclusive")

    capacities = parse_capacities(args.sem_capacity)
    if capacities is None:
        parser.error("--sem-capacity takes name=N with N >= 1")
    if (args.root or args.compare_relationships) and not args.from_github:
        parser.error("--root and --compare-relationships require --from-github")
    trust_flags = args.trust or args.trust_owner or args.trust_repo or args.trust_codeowners
    if trust_flags and not args.from_github:
        parser.error("--trust, --trust-owner, --trust-repo and --trust-codeowners require --from-github")
    if any(not OWNER_RE.fullmatch(o) for o in args.trust_owner) or any(not SLUG_RE.fullmatch(r) for r in args.trust_repo):
        parser.error("--trust-owner takes an owner name; --trust-repo takes owner/repo")
    trust = {"owners": args.trust_owner, "repos": args.trust_repo, "logins": args.trust, "codeowners": args.trust_codeowners}

    repo = os.path.abspath(args.repo)
    if args.from_github:
        return compile_from_github(repo, args.root, args.min_confidence, args.emit_mermaid, args.add_edge, args.remove_edge, args.reason, emit_roadmap=args.emit_roadmap, capacities=capacities, compare=args.compare_relationships, trust=trust)
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
