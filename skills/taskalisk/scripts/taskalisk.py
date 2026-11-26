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
cached; the only file written is the run's Parley receipt.

Output (docs/topics/output/README.md): every line on stdout and stderr is a
JSON object written through the vendored Parley writer (parley_emit.py, pinned
by parley_emit.pin.json), with a declared, separately versioned schema under
skills/taskalisk/schemas/. `--help`, `--schema`, `--human` and `--dry-run` are
the writer's. Exit 0 success, 2 a reported error, 3 a usage error before the
run started, 4 an output or receipt failure.

Commands (the 1.x mode flags still select them):
  plan       --from-github [--root <ref>] [--emit-mermaid | --emit-roadmap] [--since-last]
      Read-only. Discovers the closure from the open home issues (or the
      roots) through `.blocked_by` and `.children`, across repositories,
      compiles the transitively-reduced DAG, ranks the Open Frontier, and
      proposes a batch that respects `.holds` and `.meters`.
      Trust flags: --trust <login>, --trust-owner <owner>, --trust-repo
      <owner/repo>, --trust-codeowners (docs/threat-model.md).
      --compare-relationships also reports drift between frontmatter edges
      and GitHub blocked_by relationships, which are an optional mirror.
  edit       --add-edge "owner/repo#1080->owner/repo#1052" [--reason "..."] | --remove-edge "..."
      Adds (or removes) the parent in the child's frontmatter `.blocked_by`,
      then recompiles. If the run fails after an added edge, the old body is
      restored.
  verify     --verify-dag dag.json [--min-confidence 0.7] [--emit-mermaid]
      Read-only. Compiles a hand-written DAG specification (input, not state).
  inventory  --repo <path> [--milestone v21.0.0]
      Read-only. Full-spectrum inventory: worktrees, unmerged branches, open
      PRs, open issues. An error on any tool failure or possible truncation.

Guarantees:
1. DAG purity: only frontmatter `.blocked_by` entries enter the graph.
2. Fail closed: any `gh`/`git` failure, unparseable JSON, or list result that
   fills its query limit is a typed error (exit 2), never an empty backlog.
3. Edges come with evidence: each edge cites the frontmatter that declares it.
   Completion comes only from the GitHub issue state.
4. Strict frontmatter: an unknown `.` key, a wrong `.id`, a container used as
   a blocker, or a malformed value fails the run (`frontmatter.invalid`, exit 2).
5. Lexical lock conflicts: `.holds` keys are lexical; a trailing `/` claims a
   subtree, so `docs/` conflicts with `docs/plans/`. A semaphore with unknown
   capacity counts as exclusive.
6. Trust gate (docs/threat-model.md): an issue is a node only when its
   repository is in the trusted scope and its author and every body editor
   are trusted. A linked PR counts only from a same-repository branch by a
   trusted author. Untrusted issues and PRs are listed, never dispatched, and
   contribute nothing to the graph, to any line, or to the receipt. Any trust
   lookup that cannot run (edit history, permission, CODEOWNERS) is an error.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable

__version__ = "2.1.2"

SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = SCRIPT_DIR.parent / "schemas"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import parley_emit as pe  # noqa: E402  (vendored, pinned by parley_emit.pin.json)

# Completed = GitHub closed. GitHub treats a closed blocker as satisfied,
# whatever the reason; "not_planned" parents are reported separately.
COMPLETED_STATUSES = {"merged", "closed", "done", "completed"}
IN_FLIGHT_STATUSES = {"ready-to-merge", "in-progress", "active", "wip", "in-review"}
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


# `scheme://user:secret@host`: a credential embedded in a URL that git or gh echoes in an error.
# A scheme is bounded (RFC 3986 names are short), so a long scheme-like word with no `://` after it,
# such as `a.a.a.…`, is not rescanned from every word boundary: the match stays linear.
URL_SCHEME = r"[a-z][a-z0-9+.-]{0,31}://"
URL_CREDENTIALS_RE = re.compile(r"(?i)\b(" + URL_SCHEME + r")[^\s/@]+@")
URL_RE = re.compile(r"(?i)\b" + URL_SCHEME + r"\S+")
# A query or fragment parameter whose name says it carries a secret; its value is redacted. The
# names are a heuristic: a secret in a parameter not named here is not found
# (docs/topics/output/README.md). A value runs to the next `&`, the fragment or white space,
# past any `;`, quote or bracket inside it, so no part of it leaks; only closing punctuation at
# its very end, which belongs to the text around the URL, is given back (`_redact_value`).
URL_SECRET_PARAM_RE = re.compile(r"(?i)([?&;#](?:access_token|token|key|secret|password|signature|sig|auth|code)=)([^&#\s]+)")
AROUND_A_URL = ".,:!?'\")>]"


def _redact_value(m: re.Match[str]) -> str:
    value = m.group(2)
    kept = value.rstrip(AROUND_A_URL)
    return m.group(1) + "[redacted]" + (value[len(kept):] if kept else "")


def sanitize_text(text: str) -> str:
    """Command output that may reach a line: no home directory, no credential inside a URL, either
    as `user:secret@` or as the value of a secret-like query or fragment parameter."""
    text = URL_CREDENTIALS_RE.sub(r"\1[redacted]@", text)
    text = URL_RE.sub(lambda m: URL_SECRET_PARAM_RE.sub(_redact_value, m.group(0)), text)
    return sanitize_home(text)


# The run being written, so discovery can record each decision in the receipt as it is made.
_RUN: Any = None


def note(decision: str, because: str, detail: Any = None) -> None:
    """One receipt step (Parley spec 5): what was decided and why. Never GitHub text an untrusted
    author wrote: ids, states, counts, logins and digests only."""
    if _RUN is not None and not _RUN.ended:
        if detail is None:
            _RUN.step(decision, because)
        else:
            _RUN.step(decision, because, detail)


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
        return False, "", sanitize_text(f"{type(exc).__name__}: {exc}")
    return (
        proc.returncode == 0,
        proc.stdout.strip(),
        sanitize_text(proc.stderr.strip()),
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
    note(f"listed {len(prs)} open pull request(s)", "a pull request marks a task in flight only from a same-repository branch by a trusted author (C4)")
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
    # The same canonical spelling as parsed references (parse_issue_ref), or the home issues never match their own .id.
    note(f"the home repository is {raw.lower()}", "gh resolves it from --repo; references compare in this lowercase spelling")
    return raw.lower()


def parse_paginated_arrays(raw: str, source: str, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    """`gh api --paginate` concatenates arrays as separate JSON documents; split them."""
    items: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    idx = 0
    text = raw.strip()
    while idx < len(text):
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError as exc:
            errors.append({"source": source, "error": f"Unparseable JSON: {exc}"})
            return []
        if not isinstance(obj, list):
            errors.append({"source": source, "error": "Expected a JSON array page"})
            return []
        items.extend(obj)
        idx = end
        while idx < len(text) and text[idx].isspace():
            idx += 1
    return items


def gh_blocked_by(repo: str, slug: str, number: int, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Return the issues that block `number`, via GitHub's native dependency API."""
    source = f"gh api repos/{slug}/issues/{number}/dependencies/blocked_by"
    ok, raw, err = run_cmd_checked(["gh", "api", "--paginate", f"repos/{slug}/issues/{number}/dependencies/blocked_by"], cwd=repo)
    if not ok:
        errors.append({"source": source, "error": err or "command failed"})
        return []
    return parse_paginated_arrays(raw, source, errors)


def gh_list_open_issues_rest(repo: str, slug: str, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Open issues of `slug` with author login, actor type and association, so the trust gate
    can reject a stranger's issue before any further query (C1, C15). Pull requests are dropped."""
    source = f"gh api repos/{slug}/issues"
    ok, raw, err = run_cmd_checked(["gh", "api", "--paginate", f"repos/{slug}/issues?state=open&per_page=100"], cwd=repo)
    if not ok:
        errors.append({"source": source, "error": err or "command failed"})
        return []
    items = [it for it in parse_paginated_arrays(raw, source, errors) if isinstance(it, dict) and not it.get("pull_request")]
    if len(items) >= GH_ISSUE_LIST_LIMIT:
        errors.append({"source": source, "error": f"Result reached {GH_ISSUE_LIST_LIMIT} issues; refusing a possibly truncated seed set"})
    note(f"listed {len(items)} open issue(s) of {slug}", "the open issues of the home repository are the seeds of discovery")
    return items


def issue_meta(obj: dict[str, Any]) -> dict[str, Any]:
    """The fields discovery keeps from a REST issue object."""
    user = obj.get("user") or {}
    return {
        "title": obj.get("title", ""), "state": str(obj.get("state", "open")).lower(), "state_reason": obj.get("state_reason"),
        "body": obj.get("body") or "", "html_url": obj.get("html_url"),
        "author": user.get("login"), "author_type": user.get("type"), "association": obj.get("author_association"),
    }


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
    # GitHub owner and repository names are case-insensitive; one canonical spelling per issue.
    return (m.group("slug").lower(), int(m.group("num")))


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
    return m.group(1).lower() if m else None


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
    source = f"gh api repos/{ref[0]}/issues/{ref[1]}"
    obj = parse_json(raw, source, errors)
    if not isinstance(obj, dict):
        if not any(e["source"] == source for e in errors):
            errors.append({"source": source, "error": "Expected a JSON object"})
        return None
    return obj


def gh_patch_body(repo: str, ref: IssueRef, body: str, errors: list[dict[str, str]]) -> bool:
    try:
        proc = subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{ref[0]}/issues/{ref[1]}", "--input", "-"],
                              cwd=repo, input=json.dumps({"body": body}), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    except (FileNotFoundError, PermissionError) as exc:
        errors.append({"source": f"gh api PATCH repos/{ref[0]}/issues/{ref[1]}", "error": sanitize_text(str(exc))})
        return False
    if proc.returncode != 0:
        errors.append({"source": f"gh api PATCH repos/{ref[0]}/issues/{ref[1]}", "error": sanitize_text(proc.stderr.strip()) or "command failed"})
        return False
    note(f"wrote the body of {node_id(*ref)}", "an edge edit replaces the whole issue body; only its .blocked_by line differs (the issue edit history is the ledger)")
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
    note(f"listed {len(set(names))} branch(es)", "a branch whose name carries an issue number is recoverable work for that issue")
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
# Associations under which a permission lookup can still say "write"; any other
# association means GitHub already reports no collaborator standing.
COLLABORATOR_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
TRUSTED_PERMISSIONS = {"admin", "maintain", "write"}


BOT_KEY_PREFIX = "bot:"


def normalize_login(login: str, actor_type: str | None = None) -> str:
    """One key per identity across GitHub surfaces, keeping bots and humans apart.

    REST names a bot `x[bot]`, GraphQL `x` with `__typename: Bot`, `gh pr list` `app/x`;
    all three become `bot:x`. A human `x` stays `x`, so allowlisting `x[bot]` never
    trusts a person who happens to own the login `x`. Allowlist a bot as `x[bot]` or `app/x`."""
    key = login.lower()
    is_bot = actor_type == BOT_TYPENAME
    if key.startswith("app/"):
        key, is_bot = key[len("app/"):], True
    if key.endswith("[bot]"):
        key, is_bot = key[: -len("[bot]")], True
    return BOT_KEY_PREFIX + key if is_bot else key
CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
UNTRUSTED_TITLE = "(untrusted issue)"
OWNER_RE = re.compile(r"[A-Za-z0-9_.-]+")
SLUG_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
BOT_TYPENAME = "Bot"
# The body and the actor of every body edit (the first edit is the creation), in one
# query, so the editors checked are the editors of the body that is parsed.
EDIT_HISTORY_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!,$after:String){"
    "repository(owner:$owner,name:$name){issue(number:$number){body "
    "userContentEdits(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{editor{login __typename}}}}}}"
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


def gh_issue_edit_history(repo: str, ref: IssueRef, errors: list[dict[str, str]]) -> dict[str, Any] | None:
    """The current body and every body editor of an issue: {"body": str, "editors": [{"login", "type"}]}.
    Every page is read; a page that claims a next page without a cursor fails the lookup (exit 2)."""
    owner, name = ref[0].split("/", 1)
    source = f"gh api graphql (edit history of {node_id(*ref)})"
    editors: list[dict[str, Any]] = []
    body: str | None = None
    after: str | None = None
    while True:
        cmd = ["gh", "api", "graphql", "-f", f"query={EDIT_HISTORY_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={ref[1]}"]
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
        if body is None:
            body = issue.get("body") or ""
        edits = issue.get("userContentEdits")
        if not isinstance(edits, dict) or not isinstance(edits.get("nodes"), list):
            # A missing connection is not "no editors"; it is an answer we cannot read.
            errors.append({"source": source, "error": "GraphQL response has no readable userContentEdits connection"})
            return None
        for node in edits["nodes"]:
            editor = (node or {}).get("editor") or {}
            editors.append({"login": editor.get("login"), "type": editor.get("__typename")})
        page = edits.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            note(f"read the body and {len(editors)} body edit(s) of {node_id(*ref)}", "every editor of the body that is parsed must be trusted (C1)")
            return {"body": body, "editors": editors}
        if not page.get("endCursor"):
            errors.append({"source": source, "error": "edit history reports another page but no cursor; refusing a partial editor list"})
            return None
        after = str(page["endCursor"])


class TrustPolicy:
    """Who may be a node. Association counts only inside the repository scope (C2)."""

    def __init__(self, repo: str, home_slug: str, owners: list[str], repos: list[str], logins: list[str], codeowners: bool, errors: list[dict[str, str]]):
        # GitHub owner, repository and login names are case-insensitive; compare them folded.
        self.repo = repo
        self.owners = {home_slug.split("/", 1)[0].lower(), *(o.lower() for o in owners)}
        self.repos = {r.lower() for r in repos}
        self.logins = {normalize_login(l) for l in logins}
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

    def login_trusted(self, slug: str, login: str | None, association: str | None = None, actor_type: str | None = None) -> tuple[bool, str]:
        """A bot is trusted only by explicit allowlist; a person by allowlist, CODEOWNERS, OWNER association, or write permission."""
        if not login:
            return False, "no login (deleted user)"
        login_key = normalize_login(login, actor_type)
        if login_key in self.logins:
            return True, "allowlisted"
        if login_key.startswith(BOT_KEY_PREFIX):
            return False, "bot actors are trusted only by --trust <login>[bot]"
        if not self.in_scope(slug):
            return False, f"{slug} is outside the trusted repositories"
        self._load_codeowners(slug)
        if login_key in self._repo_logins.get(slug.lower(), set()):
            return True, "CODEOWNERS"
        if association in TRUSTED_ASSOCIATIONS:
            return True, f"association {association}"
        if association is not None and association not in COLLABORATOR_ASSOCIATIONS:
            # GitHub already says this person has no collaborator standing here; no lookup needed.
            return False, f"association {association}"
        return self._collaborator(slug, login)

    def author_trusted(self, slug: str, meta: dict[str, Any]) -> tuple[bool, list[str]]:
        """The author check needs only the REST issue object, so a stranger's issue costs no further query."""
        ok, why = self.login_trusted(slug, meta.get("author"), meta.get("association"), meta.get("author_type"))
        return ok, [] if ok else [f"author {meta.get('author') or '(none)'}: {why}"]

    def editors_trusted(self, slug: str, author: str | None, editors: list[dict[str, Any]], author_type: str | None = None) -> tuple[bool, list[str]]:
        """Every body editor other than the (already trusted) author must be trusted.
        Identities are compared with their actor type, so a bot sharing the author's login is still checked."""
        reasons: list[str] = []
        seen: set[str | None] = {normalize_login(author, author_type) if author else None}
        for editor in editors:
            login = editor.get("login")
            key = normalize_login(login, editor.get("type")) if login else None
            if key in seen:
                continue
            seen.add(key)
            ok, why = self.login_trusted(slug, login, None, editor.get("type"))
            if not ok:
                reasons.append(f"editor {login or '(none)'}: {why}")
        return not reasons, reasons

    def _collaborator(self, slug: str, login: str) -> tuple[bool, str]:
        """Trusted only with write, maintain or admin permission. A lookup that cannot run is a run error (exit 2):
        a silently untrusted collaborator would hide trusted work as opaque blockers."""
        key = (slug.lower(), login.lower())
        if key not in self._collaborator_cache:
            source = f"gh api repos/{slug}/collaborators/{login}/permission"
            ok, raw, err = run_cmd_checked(["gh", "api", f"repos/{slug}/collaborators/{login}/permission", "--jq", ".permission"], cwd=self.repo)
            if ok:
                note(f"{login} has permission {raw or 'none'} on {slug}", "write, maintain or admin trusts a person; anything less does not (C1)")
            if ok and raw in TRUSTED_PERMISSIONS:
                self._collaborator_cache[key] = (True, f"permission {raw}")
            elif ok:
                self._collaborator_cache[key] = (False, f"permission {raw or 'none'} on {slug} is below write")
            elif "HTTP 404" in err:
                self._collaborator_cache[key] = (False, f"not a collaborator of {slug}")
            else:
                self.errors.append({"source": source, "error": err or "command failed"})
                self._collaborator_cache[key] = (False, "permission lookup failed; see github_errors")
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
                note(f"read {path} of {slug}", "--trust-codeowners trusts the logins it names in that repository only (C18)")
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
        for iss in gh_list_open_issues_rest(repo, slug, errors):
            r = (slug, int(iss["number"]))
            fetched[r] = issue_meta(iss)
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
                ref_slug = f"{owner}/{repo_info['name']}".lower() if owner and repo_info.get("name") else slug
                closes.append((ref_slug, int(ref["number"])))
        if not closes:
            continue
        author = (pr.get("author") or {}).get("login")
        cross = pr.get("isCrossRepository")
        ok, why = (False, "head is not a branch of this repository") if cross is not False else policy.login_trusted(slug, author, None, "Bot" if (pr.get("author") or {}).get("is_bot") else None)
        if errors:
            return empty
        if not ok:
            untrusted_prs.append({"number": pr.get("number"), "url": pr.get("url"), "author": author, "cross_repository": cross, "closes": [node_id(*c) for c in closes], "reason": why})
            continue
        if not isinstance(pr.get("isDraft"), bool):
            errors.append({"source": "gh pr list", "error": f"PR {pr.get('number')} has no boolean isDraft; refusing an unknown review state"})
            return empty
        for c in closes:
            prs_by_issue[c].append({"number": pr["number"], "isDraft": pr["isDraft"], "url": pr.get("url")})

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
            note(f"did not fetch {nid}", "it is outside the trusted repositories (C2)")
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
            if actual[0].lower() != ref[0].lower() or actual[1] != ref[1]:
                moved = node_id(*actual)
                for who in referenced_by[ref] or [nid]:
                    violations.setdefault(who, []).append(f"reference {nid} moved to {moved} (transferred); update the frontmatter")
                continue
            fetched[ref] = issue_meta(obj)
            note(f"read {nid}", f"referenced by {', '.join(referenced_by[ref]) or 'no node (a seed)'}", {"state": fetched[ref]["state"]})
        meta = fetched[ref]
        # Author first, from the REST object: a stranger's issue costs no further query (C1, C15).
        trusted, reasons = policy.author_trusted(ref[0], meta)
        if not trusted:
            note(f"{nid} is untrusted", "; ".join(reasons))
        if trusted:
            history = gh_issue_edit_history(repo, ref, errors)
            if history is None:
                break
            meta["body"] = history["body"]  # the body whose editors were checked
            trusted, reasons = policy.editors_trusted(ref[0], meta.get("author"), history["editors"], meta.get("author_type"))
            note(f"{nid} is {'trusted' if trusted else 'untrusted'}", "; ".join(reasons) or "its author and every body editor passed the trust gate (C1)")
        if errors:
            break
        if not trusted:
            # No title: nothing an untrusted author wrote reaches any output (C3).
            untrusted.append({"id": nid, "url": meta["html_url"], "state": meta["state"], "author": meta.get("author"), "reasons": reasons, "referenced_by": referenced_by[ref]})
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
        if linked:
            status = "in-review" if any(not pr["isDraft"] for pr in linked) else "wip"
        elif status == "active":
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
            # A line break in a title would end the label (C5): fold every run of whitespace into one space.
            safe_label = " ".join(f"{nid}: {title}".split()).replace('"', "'").replace("<", "(").replace(">", ")").replace("[", "(").replace("]", ")")
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


def _resources_cell(holds: list[str], meters: list[dict[str, Any]], empty: str, in_table: bool) -> str:
    """Each hold and meter as a code span, shown as written (`_md_code`)."""
    cells = [_md_code(k, in_table) for k in holds] + [_md_code(f"{m['name']}*{m['slots']}", in_table) for m in meters]
    return ", ".join(cells) or empty


def _md_code(text: str, in_table: bool) -> str:
    """Text as a code span, which shows its characters literally and never links: line breaks fold
    to a space, controls are dropped, and the fence is one backtick longer than the longest run of
    backticks inside (padded with a space when the text starts or ends with a backtick or a space;
    an empty result is shown as an em dash). In a table, `|`
    must still be written `\\|`, the one escape GFM reads inside a code span there."""
    text = MD_CONTROL_RE.sub("", MD_LINE_BREAK_RE.sub(" ", str(text)))
    if in_table:
        text = text.replace("|", "\\|")
    if not text:
        return "\u2014"  # nothing left to show
    fence = "`" * (max((len(r) for r in re.findall("`+", text)), default=0) + 1)
    # GFM strips one space from each end when both are spaces, and a backtick at an end would join
    # the fence: padding either keeps the text as written.
    pad = " " if text[0] in "` " or text[-1] in "` " else ""
    return f"{fence}{pad}{text}{pad}{fence}"


MD_LINE_BREAK_RE = re.compile("\r\n|[\n\r\x0b\x0c\x85\u2028\u2029]")
# C0 and C1 controls and the bidirectional controls (embeddings, overrides, isolates, marks).
MD_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
# Where GFM can start a link: every scheme's `://` and every `www.`, whatever comes before them
# (a letter, a digit, `_` or punctuation is no guard GitHub's renderer honours), and an `@` before
# any non-space character (an email address, `mailto:` or a mention). A bounded scheme keeps the
# scan linear.
MD_AUTOLINK_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]{0,31}:)(//)|(www)(\.)|(@)(?=\S)")
# A character reference GFM decodes before it looks for links (`&#64;` is `@`); its `&` is escaped.
MD_CHAR_REF_RE = re.compile(r"&(?=#[0-9]{1,7};|#[xX][0-9a-fA-F]{1,6};|[A-Za-z][A-Za-z0-9]{1,31};)")
ZERO_WIDTH_SPACE = "\u200b"


def _unlink(m: re.Match[str]) -> str:
    """The match with a zero-width space where GFM would see the start of a link."""
    if m.group(1):
        return m.group(1) + ZERO_WIDTH_SPACE + m.group(2)
    if m.group(3):
        return m.group(3) + ZERO_WIDTH_SPACE + m.group(4)
    return m.group(5) + ZERO_WIDTH_SPACE


def _md_cell(text: str) -> str:
    """Issue text in a rendered table cell: no pipes, no HTML, no links, no line breaks, no control
    characters (C5). In order: the backslash is escaped first, so a title's own backslash cannot
    cancel a later escape; every Unicode line break becomes a space; every other C0 or C1 control
    character (ESC included) and every bidirectional control is dropped; the `&` of a character
    reference becomes `&amp;`, so `&#64;` stays text; `|`, `[`, `]` are escaped and `<`, `>`
    become entities; and nothing can autolink, because a zero-width space (U+200B) follows the
    colon of every `scheme://`, the `www` of every `www.` and an `@` before any non-space
    character (`_unlink`). Text that needs none of this is returned unchanged."""
    text = str(text).replace("\\", "\\\\")
    text = MD_CONTROL_RE.sub("", MD_LINE_BREAK_RE.sub(" ", text))
    text = MD_CHAR_REF_RE.sub("&amp;", text)
    text = text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;").replace("[", "\\[").replace("]", "\\]")
    return MD_AUTOLINK_RE.sub(_unlink, text)


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
            f"{n['transitive_unblocks_count']} | {n['critical_path_remaining_depth']} | {_resources_cell(n['holds'], n['meters'], '—', in_table=True)} | "
            f"{', '.join(n['directly_unlocks']) or '—'} |"
        )
    out += ["", "### Conflict-Free git-locks Batch", ""]
    for b in result.get("conflict_free_frontier_batch", []):
        out.append(f"- {_issue_link(b['id'], b.get('url'))} {_md_cell(b['title'])} — {_resources_cell(b['holds'], b['meters'], 'no resources', in_table=False)}")
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


def mutate_edge(repo: str, home: str, parent: IssueRef, child: IssueRef, add: bool, errors: list[dict[str, str]], policy: TrustPolicy, write: bool = True) -> dict[str, Any] | None:
    """Edit the child's frontmatter .blocked_by. Returns {"child": ref, "old_body": str} or None.
    With write False (a --dry-run) every check runs and nothing is written."""
    # The child is always checked. The parent's scope matters only when an edge is added:
    # removing a reference to an out-of-scope issue is how an operator repairs such a reference.
    for ref in ((parent, child) if add else (child,)):
        if not policy.in_scope(ref[0]):
            errors.append({"source": f"edge {node_id(*parent)}->{node_id(*child)}", "error": f"{node_id(*ref)} is outside the trusted repositories"})
            return None
    obj = gh_get_issue(repo, child, errors)
    if obj is None:
        return None
    if obj.get("pull_request"):
        errors.append({"source": f"edge {node_id(*parent)}->{node_id(*child)}", "error": f"{node_id(*child)} is a pull request, not an issue"})
        return None
    meta = issue_meta(obj)
    trusted, reasons = policy.author_trusted(child[0], meta)
    body = meta["body"]
    if trusted:
        history = gh_issue_edit_history(repo, child, errors)
        if history is None:
            return None
        body = history["body"]
        trusted, reasons = policy.editors_trusted(child[0], meta.get("author"), history["editors"], meta.get("author_type"))
    if errors:
        # A trust lookup that recorded an error (for example a failed CODEOWNERS fetch) never permits a write.
        return None
    if not trusted:
        # Never write into a stranger's issue, even with the permission to do so (C3).
        errors.append({"source": f"frontmatter of {node_id(child[0], child[1], home)}", "error": "child is untrusted: " + "; ".join(reasons)})
        return None
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
    if write and new_body != body and not gh_patch_body(repo, child, new_body, errors):
        return None
    return {"child": child, "old_body": body, "changed": new_body != body}


def parse_capacities(items: list[str]) -> dict[str, int] | None:
    caps: dict[str, int] = {}
    for item in items:
        name, _, num = item.partition("=")
        if not name or not num.isdigit() or int(num) < 1:
            return None
        caps[name] = int(num)
    return caps


# --------------------------------------------------------------------------- #
# Output: every line through Parley (docs/topics/output/README.md)
# --------------------------------------------------------------------------- #

SCHEMA_VERSION = "1.0.0"
MESSAGES = ("plan", "frontier_node", "node", "wave", "batch", "edge", "finding", "edge_edit", "rendering", "frontier_change",
            "inventory.summary", "inventory.worktree", "inventory.branch", "inventory.pull_request", "inventory.issue")
COMMANDS = ("plan", "edit", "verify", "inventory")
# Every token variable `gh help environment` names; their values are scrubbed from every line and
# named in the receipt head (spec 5.3).
SECRETS = ["GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"]
OBSERVATIONS_INPUT = "github:issues"
INVENTORY_INPUT = "github+git:inventory"
RETENTION = 50


def schema_ref(name: str) -> tuple[str, str]:
    return (f"taskalisk.{name}", SCHEMA_VERSION)


def load_schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / f"taskalisk.{name}.schema.json").read_text(encoding="utf-8"))


def emits(*names: str) -> list[dict[str, Any]]:
    return [{"id": f"taskalisk.{n}", "version": SCHEMA_VERSION, "schema": load_schema(n)} for n in names]


def sha256_text(text: Any) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


# ---- the score and its terms --------------------------------------------------------------


def score_terms(node: dict[str, Any]) -> dict[str, Any]:
    """priority_score as its terms. compile_and_analyze_dag computes the total; this states it."""
    status = str(node.get("status", "")).strip().lower()
    values = [
        ("in_flight", 1 if status in IN_FLIGHT_STATUSES else 0, PRIORITY_IN_FLIGHT_WEIGHT),
        ("parked", 1 if status == PARKED_STATUS else 0, PRIORITY_PARKED_WEIGHT),
        ("descendants", node["transitive_unblocks_count"], PRIORITY_DESCENDANTS_WEIGHT),
        ("critical_path_depth", node["critical_path_remaining_depth"], PRIORITY_DEPTH_WEIGHT),
        ("out_degree", len(node["directly_unlocks"]), 1),
    ]
    terms = {name: {"value": v, "weight": w, "points": v * w} for name, v, w in values}
    total = sum(t["points"] for t in terms.values())
    if total != node["priority_score"]:
        raise AssertionError(f"the terms of {node['id']} sum to {total}, not its priority_score {node['priority_score']}")
    return {"total": total, "terms": terms}


# ---- failures as typed errors -------------------------------------------------------------

REMEDIES = {
    "gh.command_failed": "check `gh auth status` and the network, then rerun; nothing was compiled from a partial read",
    "gh.list_limit_reached": "narrow the seeds with --root; a list that fills its limit may be truncated (threat model C15)",
    "gh.response_invalid": "report the gh version with the receipt; a malformed answer is not fixed by running again",
    "gh.mutation_failed": "check the token can edit issues in that repository, then rerun",
    "git.command_failed": "run the command shown in detail.source inside --repo to see why",
    "root.invalid_reference": "name the root as owner/repo#N",
    "root.out_of_scope": "add --trust-owner or --trust-repo for that repository, or choose a root inside the scope",
    "edge.out_of_scope": "add --trust-owner or --trust-repo, or choose an issue inside the scope",
    "edge.child_not_issue": "name the pull request's issue as the child",
    "edge.child_untrusted": "never write into a stranger's issue; a trusted person files their own issue",
    "edge.child_frontmatter_missing": "give the child valid issue-dag/2 task frontmatter first",
    "edge.child_frontmatter_invalid": "fix the child's frontmatter first; the run's frontmatter.violation findings say how",
    "edge.rewrite_impossible": "the child's frontmatter needs exactly one .blocked_by line",
}

# Whether a retry can help, for each code `classify` returns. docs/topics/output/README.md and
# SKILL.md state the same flags; tests/test_parley_output.py holds the three together.
RETRYABLE = {
    "gh.command_failed": True,
    "gh.list_limit_reached": False,
    "gh.response_invalid": False,
    "gh.mutation_failed": True,
    "git.command_failed": True,
    "root.invalid_reference": False,
    "root.out_of_scope": False,
    "edge.out_of_scope": False,
    "edge.child_not_issue": False,
    "edge.child_untrusted": False,
    "edge.child_frontmatter_missing": False,
    "edge.child_frontmatter_invalid": False,
    "edge.rewrite_impossible": False,
}


def classify(err: dict[str, str]) -> tuple[str, bool]:
    """A stable code, and whether a retry can help (`RETRYABLE`), for one failure the compiler records."""
    code = error_code(err)
    return code, RETRYABLE[code]


def error_code(err: dict[str, str]) -> str:
    """The stable code for one failure the compiler records."""
    src, msg = err["source"], err["error"]
    if "possible truncation" in msg or "possibly truncated" in msg:
        return "gh.list_limit_reached"
    if src == "--root":
        return "root.out_of_scope" if "outside the trusted" in msg else "root.invalid_reference"
    if src.startswith("edge "):
        return "edge.child_not_issue" if "pull request" in msg else "edge.out_of_scope"
    if src.startswith("frontmatter of "):
        if msg.startswith("child is untrusted"):
            return "edge.child_untrusted"
        if msg.startswith("missing or unparseable"):
            return "edge.child_frontmatter_missing"
        if msg.startswith("invalid task frontmatter"):
            return "edge.child_frontmatter_invalid"
        return "edge.rewrite_impossible"
    if src.startswith("gh api PATCH"):
        return "gh.mutation_failed"
    if any(k in msg for k in ("Unparseable JSON", "Expected a JSON", "GraphQL response has no", "no cursor", "isDraft", "repository_url")):
        return "gh.response_invalid"
    if src.startswith("git"):
        return "git.command_failed"
    return "gh.command_failed"


def one_sentence(text: str, limit: int = 600) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


class Failure:
    """One parley.error to report: a stable code, one sentence, and the detail a caller acts on."""

    def __init__(self, code: str, problem: str, detail: dict[str, Any] | None = None, remedy: str | None = None, retryable: bool | None = None):
        self.code, self.problem, self.detail, self.remedy, self.retryable = code, problem, detail, remedy, retryable

    @classmethod
    def from_lookup(cls, err: dict[str, str], phase: str) -> "Failure":
        code, retryable = classify(err)
        return cls(code, one_sentence(f"{err['source']}: {err['error']}"), {"source": err["source"], "error": err["error"], "phase": phase},
                   REMEDIES.get(code), retryable)

    def report(self, run: Any) -> None:
        run.error(self.code, self.problem, remedy=self.remedy, retryable=self.retryable, detail=self.detail)


# ---- the plan from GitHub -----------------------------------------------------------------


class Outcome:
    """What a plan or an edit computed, before a line of it is written."""

    def __init__(self) -> None:
        self.result: dict[str, Any] | None = None
        self.source: dict[str, Any] | None = None
        self.mutation: dict[str, Any] | None = None
        self.failures: list[Failure] = []
        self.rel_failed = False


def rollback(outcome: Outcome, repo: str, undo: dict[str, Any] | None) -> None:
    """Restore the child's body after an added edge, whatever made the run fail (doctrine 8)."""
    m = outcome.mutation
    if not (m and m["type"] == "add_blocked_by" and undo and undo["changed"]) or "rolled_back" in m:
        return
    rb_errors: list[dict[str, str]] = []
    m["rolled_back"] = gh_patch_body(repo, undo["child"], undo["old_body"], rb_errors)
    if rb_errors:
        m["rollback_errors"] = rb_errors
    note(f"restored the body of {m['child']}" if m["rolled_back"] else f"could not restore the body of {m['child']}",
         "an added edge is undone when the run that would have checked it fails")


def rollback_failure(outcome: Outcome) -> list[Failure]:
    """The error for an added edge that could not be removed again, on every path that tried."""
    m = outcome.mutation
    if not (m and m.get("rolled_back") is False):
        return []
    return [Failure("edge.rollback_failed", f"the added edge {m['parent']}->{m['child']} could not be removed again",
                    {"rollback_errors": m.get("rollback_errors", [])}, "remove it by hand with edit --remove-edge", True)]


def github_plan(repo: str, roots: list[str], min_confidence: float, add_edge: str | None, remove_edge: str | None, reason: str,
                capacities: dict[str, int] | None, compare: bool, trust: dict[str, Any], dry_run: bool, out: Outcome | None = None) -> Outcome:
    """The 1.x compile, unchanged in what it computes: the same result document, the same hash.

    `out` is filled in place, so a caller still holds the mutation if an exception escapes. An
    exception after an added edge's write, before the compile has admitted the edit, undoes it."""
    out = Outcome() if out is None else out
    errors: list[dict[str, str]] = []
    undo: dict[str, Any] | None = None
    if add_edge or remove_edge:
        parsed = parse_edge_arg(add_edge or remove_edge or "")
        assert parsed is not None and parsed[0] != parsed[1], "resolve() checks the edge before the bootstrap line"
        parent, child = parsed
        slug = gh_repo_slug(repo, errors)
        if slug is None:
            out.failures += [Failure.from_lookup(e, "edge_edit") for e in errors]
            return out
        policy = TrustPolicy(repo, slug, trust.get("owners", []), trust.get("repos", []), trust.get("logins", []), bool(trust.get("codeowners")), errors)
        undo = mutate_edge(repo, slug, parent, child, add=bool(add_edge), errors=errors, policy=policy, write=not dry_run)
        if undo is None:
            out.failures += [Failure.from_lookup(e, "edge_edit") for e in errors]
            return out
        child_id = node_id(child[0], child[1], slug)
        out.mutation = {"type": "add_blocked_by" if add_edge else "remove_blocked_by", "parent": node_id(parent[0], parent[1], slug), "child": child_id,
                        "changed": undo["changed"], "reason": reason, "recorded_in": f"frontmatter of {child_id} (the issue edit history is the ledger)"}
        if dry_run:
            # A dry run checks the edit and writes nothing; the graph it would compile is the one without the edit.
            out.mutation["dry_run"] = True
            note("dry run: wrote nothing and compiled nothing", "a dry run performs no subject-matter write (spec 4.3), and the unedited graph would not answer the question")
            return out

    try:
        return compile_github(out, repo, roots, min_confidence, capacities, compare, trust, errors, undo)
    except BaseException:
        if out.result is None or not out.result.get("ok"):
            rollback(out, repo, undo)  # the compile never admitted the edit (doctrine 8)
        raise


def compile_github(out: Outcome, repo: str, roots: list[str], min_confidence: float, capacities: dict[str, int] | None,
                   compare: bool, trust: dict[str, Any], errors: list[dict[str, str]], undo: dict[str, Any] | None) -> Outcome:
    """Discovery and the compile, after any edit; an edit that does not compile is rolled back."""
    source = collect_frontmatter_dag(repo, roots, errors, trust)
    if errors:
        out.failures += [Failure.from_lookup(e, "discovery") for e in errors]
        rollback(out, repo, undo)
        out.failures += rollback_failure(out)
        return out
    out.source = source

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
    rel_errors: list[dict[str, str]] = []
    if compare:
        result["relationship_drift"] = compare_relationships(repo, source, rel_errors)
    if rel_errors:
        # A failed gh call is never an empty drift report (doctrine 4); the run fails below, after any rollback.
        result["ok"] = False
        result["error"] = "GitHub relationship lookup failed"
        result["github_errors"] = rel_errors
    if out.mutation:
        result["mutation"] = out.mutation
    if not result.get("ok"):
        rollback(out, repo, undo)
    out.result = with_artifact_hash(result)
    out.rel_failed = bool(rel_errors)

    if "cyclic_nodes" in result:
        out.failures.append(Failure("graph.cycle", result["error"], {"cyclic_nodes": result["cyclic_nodes"]},
                                    "split the shared foundation into a predecessor issue, or remove the edge that closes the cycle", False))
    elif "metrics" not in result:
        out.failures.append(Failure("graph.unresolved_prerequisites", result["error"],
                                    {"unknown": len(result.get("unknown_dependencies", [])), "stale_merged_hints": len(result.get("stale_merged_hints", []))},
                                    "fix the references the prerequisite findings name", False))
    if source["violations"]:
        out.failures.append(Failure("frontmatter.invalid", f"{len(source['violations'])} issue(s) have invalid frontmatter",
                                    {"violating_issues": sorted(source["violations"], key=id_sort_key)},
                                    "fix each frontmatter.violation finding; do not dispatch from this plan", False))
    out.failures += [Failure.from_lookup(e, "relationships") for e in rel_errors]
    out.failures += rollback_failure(out)
    return out


def observations(fetched: dict[IssueRef, dict[str, Any]]) -> list[dict[str, Any]]:
    """What discovery read, by id and digest only: never a title or body (threat model C3)."""
    return [{"id": node_id(*ref), "state": meta["state"], "state_reason": meta.get("state_reason"),
             "title_sha256": sha256_text(meta.get("title")), "body_sha256": sha256_text(meta.get("body"))}
            for ref, meta in sorted(fetched.items(), key=lambda kv: (kv[0][0], kv[0][1]))]


def supply_observations(run: Any, fetched: dict[IssueRef, dict[str, Any]]) -> None:
    items = observations(fetched)
    note(f"observed {len(items)} issue(s)", "issue bodies are declared inputs by digest and id; the input's digest is over this list (docs/topics/output)", {"issues": items})
    run.input(OBSERVATIONS_INPUT, pe.canonical(items))


# ---- writing the lines ----------------------------------------------------------------------

FINDING_ORDER = ("container.excluded", "issue.unmodeled", "issue.untrusted", "pull_request.untrusted", "issue.opaque", "parent.not_planned",
                 "frontmatter.violation", "frontmatter.warning", "edge.redundant", "edge.soft_or_low_confidence", "prerequisite.unknown",
                 "prerequisite.stale_merged_hint", "graph.cyclic_node", "relationship.only_in_frontmatter", "relationship.only_in_github",
                 "since_last.no_previous")


def finding_lines(result: dict[str, Any], source_doc: dict[str, Any] | None, drift_ok: bool) -> list[dict[str, Any]]:
    """Every finding, in FINDING_ORDER; each message is built from ids, states, logins and the rule."""
    f: list[dict[str, Any]] = []

    def add(code: str, message: str, subject: str | None = None, detail: dict[str, Any] | None = None) -> None:
        line: dict[str, Any] = {"event": "finding", "code": code}
        if subject:
            line["subject"] = subject
        line["message"] = message
        if detail is not None:
            line["detail"] = detail
        f.append(line)

    src = source_doc or {}
    for c in src.get("containers_excluded", []):
        add("container.excluded", f"{c['id']} is a container: its children are nodes and it is not", c["id"], c)
    for u in src.get("unmodeled_open_issues", []):
        add("issue.unmodeled", f"{u['id']} is an open home issue without frontmatter; it is not a node", u["id"], u)
    for u in src.get("untrusted_issues", []):
        add("issue.untrusted", f"{u['id']} failed the trust gate: {'; '.join(u['reasons'])}", u["id"], u)
    for pr in src.get("untrusted_linked_prs", []):
        add("pull_request.untrusted", f"pull request {pr.get('number')} closing {', '.join(pr['closes'])} has no effect: {pr['reason']}", None, pr)
    for o in src.get("opaque_nodes", []):
        add("issue.opaque", f"{o['id']} has no frontmatter; it blocks {', '.join(o['referenced_by']) or 'nothing'} until it closes", o["id"], o)
    for n in src.get("not_planned_parents", []):
        add("parent.not_planned", f"{n['parent']} closed as not planned and still satisfies the edge to {n['child']}; review it", n["parent"], n)
    fm = result.get("frontmatter") or {}
    for nid in sorted(fm.get("violations", {}), key=id_sort_key):
        for v in fm["violations"][nid]:
            add("frontmatter.violation", v, nid)
    for nid in sorted(fm.get("warnings", {}), key=id_sort_key):
        for w in fm["warnings"][nid]:
            add("frontmatter.warning", w, nid)
    for e in result.get("transitive_redundant_edges_removed", []):
        add("edge.redundant", f"{e['from']} -> {e['to']} is implied via {e['implied_via']}", f"{e['from']}->{e['to']}", e)
    for e in result.get("soft_or_low_confidence_edges", []):
        add("edge.soft_or_low_confidence", f"{e['from']} -> {e['to']} is soft or below the confidence threshold ({e['confidence']})", f"{e['from']}->{e['to']}", e)
    for u in result.get("unknown_dependencies", []):
        add("prerequisite.unknown", f"{u['node']} names {u['unknown_prerequisite']}, which is neither open nor completed", u["node"], u)
    for h in result.get("stale_merged_hints", []):
        add("prerequisite.stale_merged_hint", f"{h['node']} marks {h['prerequisite']} merged, but it is {h['prerequisite_status']}", h["node"], h)
    for nid in result.get("cyclic_nodes", []):
        add("graph.cyclic_node", f"{nid} is on or behind a cycle of hard edges", nid)
    drift = result.get("relationship_drift") if drift_ok else None
    for key, code, where in (("only_in_frontmatter", "relationship.only_in_frontmatter", "is in frontmatter but not in GitHub's blocked_by relationships"),
                             ("only_in_github", "relationship.only_in_github", "is a GitHub blocked_by relationship that frontmatter lacks")):
        for text in (drift or {}).get(key, []):
            a, _, b = text.partition(" -> ")
            add(code, f"{text} {where}", f"{a}->{b}", {"from": a, "to": b})
    return f


def wave_number(label: str) -> int:
    return int(label.rsplit(" ", 1)[1])


def node_fields(n: dict[str, Any]) -> dict[str, Any]:
    """A node as its line carries it. A `.size_hours` that is not an integer is already a
    frontmatter.violation (the plan is not ok); the line says null rather than fail its schema. The
    result document, and so `artifact_hash`, keeps the 1.x value."""
    size = n.get("size_hours")
    if size is None or (isinstance(size, int) and not isinstance(size, bool)):
        return n
    return {**n, "size_hours": None}


def emit_plan(run: Any, result: dict[str, Any], mode: str, failures: list[Failure], since: dict[str, Any] | None,
              rendering: str | None, rel_failed: bool = False, mutation: dict[str, Any] | None = None) -> None:
    """Plan summary first (the smallest line that answers 'what next'), the frontier in rank order,
    the batch, then everything else; errors last (docs/topics/output)."""
    if mutation is not None:
        run.result({"event": "edge_edit", **mutation}, schema_ref("edge_edit"))
    compiled = "metrics" in result
    outcome = "compiled" if compiled else ("cycle" if "cyclic_nodes" in result else "unresolved")
    codes = [f.code for f in failures]
    plan: dict[str, Any] = {"event": "plan", "mode": mode, "outcome": outcome, "ok": bool(result.get("ok")), "error_codes": codes,
                            "artifact_hash": result["meta"]["artifact_hash"]}
    src = result.get("source")
    if src is not None:
        plan["source"] = {k: src[k] for k in ("kind", "schema", "repository", "roots", "trust")}
    if compiled:
        plan["metrics"] = result["metrics"]
        plan["open_frontier_count"] = result["open_frontier_count"]
        plan["frontier"] = [n["id"] for n in result["open_frontier_ranked"]]
        plan["batch"] = [b["id"] for b in result["conflict_free_frontier_batch"]]
    if src is not None:
        plan["violating_issues"] = result["frontmatter"]["violating_issues"]
        drift = result.get("relationship_drift")
        plan["relationships"] = {"compared": drift is not None, **({"in_sync": None if rel_failed else drift["in_sync"]} if drift is not None else {})}
    if since is not None:
        plan["since_last"] = {"compared_with": since["run"], "changes": len(since["changes"])}
    run.result(plan, schema_ref("plan"))
    if compiled:
        for rank, n in enumerate(result["open_frontier_ranked"], 1):
            run.result({"event": "frontier_node", "rank": rank, "wave": 0, **node_fields(n), "score": score_terms(n)}, schema_ref("frontier_node"))
        run.result({"event": "batch", "members": result["conflict_free_frontier_batch"], "skipped": result["batch_skipped"],
                    "semaphores_with_unknown_capacity_treated_as_1": result["semaphores_with_unknown_capacity_treated_as_1"]}, schema_ref("batch"))
    for change in (since or {}).get("changes", []):
        run.result({"event": "frontier_change", **change}, schema_ref("frontier_change"))
    if compiled:
        for label, items in result["waves"].items():
            k = wave_number(label)
            if k:
                for n in items:
                    run.result({"event": "node", "wave": k, **node_fields(n)}, schema_ref("node"))
        for label, items in result["waves"].items():
            run.result({"event": "wave", "wave": wave_number(label), "label": label, "ids": [n["id"] for n in items]}, schema_ref("wave"))
        for e in result["edges"]:
            run.result({"event": "edge", **e}, schema_ref("edge"))
    for line in finding_lines(result, src, drift_ok=not rel_failed):
        run.result(line, schema_ref("finding"))
    if since is not None and since["run"] is None:
        run.result({"event": "finding", "code": "since_last.no_previous",
                    "message": "no earlier completed receipt of taskalisk in this working directory asked the same question; nothing was compared"}, schema_ref("finding"))
    if rendering is not None and result.get("ok"):
        fmt = rendering
        text = render_roadmap_block(result) if fmt == "roadmap" else render_mermaid_flowchart(result)
        run.result({"event": "rendering", "format": fmt, "text": text}, schema_ref("rendering"))
    for f in failures:
        f.report(run)


# ---- --since-last: the previous plan, from its receipt alone --------------------------------


def read_receipt(path: Path) -> list[dict[str, Any]] | None:
    """A receipt's lines with each sidecar replaced by the record it holds; None when unreadable or incomplete."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not raw.endswith("\n"):
        return None
    lines: list[dict[str, Any]] = []
    for text in raw.splitlines():
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        if obj.get("event") == "sidecar":
            rel = str(obj.get("path", ""))
            target = (path.parent / rel).resolve()
            if not str(target).startswith(str(path.parent.resolve()) + os.sep):
                return None
            try:
                obj = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        lines.append(obj)
    return lines


def positions_from_lines(lines: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    pos: dict[str, dict[str, int]] = {}
    for line in lines:
        sid = (line.get("_schema") or {}).get("id")
        if sid == "taskalisk.frontier_node":
            pos[line["id"]] = {"wave": 0, "rank": line["rank"]}
        elif sid == "taskalisk.node":
            pos[line["id"]] = {"wave": line["wave"]}
    return pos


def positions_from_result(result: dict[str, Any]) -> dict[str, dict[str, int]]:
    pos: dict[str, dict[str, int]] = {}
    for label, items in result.get("waves", {}).items():
        k = wave_number(label)
        for rank, n in enumerate(items, 1):
            pos[n["id"]] = {"wave": 0, "rank": rank} if k == 0 else {"wave": k}
    return pos


NODE_ID_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*")
COMPARED_LINES = ("plan", "frontier_node", "node")
RUN_ID_RE = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")  # a ULID, which is what the writer mints (Parley spec 2.1)


def unbelievable(name: str, lines: list[dict[str, Any]]) -> str | None:
    """Why a receipt in the directory is not one this tool wrote, or None. A receipt is a local file
    anyone with the directory can write, so --since-last compares only with one whose name is its
    run, whose compared lines validate against the exact schema they name, and whose ids are issues."""
    if name != f"{lines[0].get('run')}.jsonl":
        return "its file name is not its run id"
    if not RUN_ID_RE.fullmatch(str(lines[0].get("run"))):
        return "its run id is not one the writer mints"
    extra = {schema_ref(m): load_schema(m) for m in COMPARED_LINES}
    for line in lines:
        ref = line.get("_schema") or {}
        if ref.get("id") in {f"taskalisk.{m}" for m in COMPARED_LINES}:
            if (ref.get("id"), ref.get("version")) not in extra or not pe.validate_line(line, extra).ok:
                return f"a {ref.get('id')} line does not validate against taskalisk {SCHEMA_VERSION}"
            if ref["id"] != "taskalisk.plan" and not NODE_ID_RE.fullmatch(str(line.get("id"))):
                return f"a {ref['id']} line names no issue"
    return None


def previous_plan(run: Any, question: dict[str, Any]) -> tuple[str, dict[str, dict[str, int]]] | None:
    """The most recent other completed receipt of this tool, in this run's receipt directory, whose
    resolved question is this one and whose plan compiled. One that fails `unbelievable` is skipped,
    with a step saying why."""
    try:
        names = sorted((n for n in os.listdir(run.receipt_dir) if n.endswith(".jsonl") and n != f"{run.id}.jsonl"), reverse=True)
    except OSError:
        return None
    for name in names:
        lines = read_receipt(Path(run.receipt_dir) / name)
        if not lines or lines[0].get("event") != "receipt.head" or lines[0].get("tool") != "taskalisk" or lines[-1].get("event") != "end":
            continue
        resolved = lines[0].get("resolved") or {}
        if resolved.get("command") not in ("plan", "edit") or resolved.get("question") != question:
            continue
        plan = next((l for l in lines if (l.get("_schema") or {}).get("id") == "taskalisk.plan"), None)
        if not plan or plan.get("outcome") != "compiled":
            continue
        why = unbelievable(name, lines)
        if why is not None:
            shown = repr(name) if RUN_ID_RE.fullmatch(name[:-len(".jsonl")]) else "with a name that is no run id"
            note(f"--since-last: ignored receipt {shown}", why)
            continue
        return str(lines[0].get("run")), positions_from_lines(lines)
    return None


def frontier_changes(previous: dict[str, dict[str, int]], current: dict[str, dict[str, int]], closed: set[str], since_run: str) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for nid in sorted(set(previous) | set(current), key=id_sort_key):
        p, c = previous.get(nid), current.get(nid)
        if c is not None and c["wave"] == 0 and (p is None or p["wave"] > 0):
            kind = "added" if p is None else "promoted"
        elif c is not None and c["wave"] > 0 and p is not None and p["wave"] == 0:
            kind = "newly_blocked"
        elif c is None and p is not None:
            kind = "closed" if nid in closed else "left"
        else:
            continue
        changes.append({"change": kind, "id": nid, "previous": p, "current": c, "since_run": since_run})
    return changes


# ---- the commands ---------------------------------------------------------------------------

STATE: dict[str, Any] = {}


def trust_of(ns: argparse.Namespace) -> dict[str, Any]:
    return {"owners": ns.trust_owner, "repos": ns.trust_repo, "logins": ns.trust, "codeowners": ns.trust_codeowners}


def run_plan(run: Any, ns: argparse.Namespace, command: str) -> None:
    repo = os.path.abspath(ns.repo)
    outcome = Outcome()
    try:
        github_plan(repo, ns.root, ns.min_confidence, ns.add_edge, ns.remove_edge, ns.reason, parse_capacities(ns.sem_capacity),
                    ns.compare_relationships, trust_of(ns), run.dry_run, out=outcome)
    except BaseException:
        # The edit happened (and may have been undone): say so before the writer reports the exception.
        if outcome.mutation is not None:
            run.result({"event": "edge_edit", **outcome.mutation}, schema_ref("edge_edit"))
            for f in rollback_failure(outcome):
                f.report(run)
        raise
    if outcome.mutation is not None:
        # First on stdout, as before, and before anything below can fail: a write is never silent.
        run.result({"event": "edge_edit", **outcome.mutation}, schema_ref("edge_edit"))
    if outcome.source is not None:
        supply_observations(run, outcome.source["fetched"])
    if outcome.result is None:
        for f in outcome.failures:
            f.report(run)
        return
    since = None
    if ns.since_last and "metrics" not in outcome.result:
        note("--since-last: not compared", "the plan did not compile, so it has no frontier to compare")
    elif ns.since_last:
        prev = previous_plan(run, STATE["resolved"]["question"])
        if prev is None:
            since = {"run": None, "changes": []}
            note("--since-last: no previous plan to compare", "no other completed receipt in this directory asked the same question")
        else:
            closed = set(outcome.source["merged"]) if outcome.source else set()
            since = {"run": prev[0], "changes": frontier_changes(prev[1], positions_from_result(outcome.result), closed, prev[0])}
            note(f"--since-last: compared with run {prev[0]}", "the most recent completed receipt of the same question in this directory", {"changes": len(since["changes"])})
    emit_plan(run, outcome.result, "github", outcome.failures, since, ns.emit, outcome.rel_failed)


def finite_number(value: Any) -> bool:
    """A JSON number a float can hold: not a bool, a string, null, NaN, an infinity, or an integer
    beyond the float range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def check_spec(data: Any) -> str | None:
    """Why a --verify-dag spec cannot be compiled, or None. Each line it yields must validate."""
    if not isinstance(data, dict) or not isinstance(data.get("nodes", {}), dict):
        return "DAG spec must be an object with a 'nodes' object"
    if not isinstance(data.get("merged", []), list):
        return "DAG spec 'merged' must be a list"
    for nid, meta in data.get("nodes", {}).items():
        if not nid:
            return "DAG spec node ids must be non-empty"
        if not isinstance(meta, dict):
            return f"DAG spec node {nid!r} must be an object"
        for key in ("title", "type", "workstream"):
            if key in meta and not isinstance(meta[key], str):
                return f"DAG spec node {nid!r}: {key} must be a string"
        if meta.get("url") is not None and not isinstance(meta["url"], str):
            return f"DAG spec node {nid!r}: url must be a string or null"
        holds = meta.get("holds", meta.get("resources", [])) or []
        if not isinstance(holds, list) or not all(isinstance(h, str) for h in holds):
            return f"DAG spec node {nid!r}: holds must be a list of strings"
        meters = meta.get("meters", []) or []
        if not isinstance(meters, list) or not all(isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"]
                                                   and isinstance(m.get("slots"), int) and not isinstance(m.get("slots"), bool) and m["slots"] >= 1 for m in meters):
            return f"DAG spec node {nid!r}: meters must be a list of {{name, slots}} with slots >= 1"
        size = meta.get("size_hours")
        if size is not None and (not isinstance(size, int) or isinstance(size, bool)):
            return f"DAG spec node {nid!r}: size_hours must be an integer or null"
        deps = meta.get("depends_on", meta.get("prerequisites", []))
        if not isinstance(deps, list) or not all(isinstance(d, (str, dict)) for d in deps):
            return f"DAG spec node {nid!r}: depends_on must be a list of ids or edge objects"
        for dep in deps:
            if not isinstance(dep, dict):
                continue
            if "isHard" in dep and not isinstance(dep["isHard"], bool):
                return f"DAG spec node {nid!r}: an edge's isHard must be true or false"
            if not finite_number(dep.get("confidence", 1.0)):
                return f"DAG spec node {nid!r}: an edge's confidence must be a finite number"
        branches = meta.get("recoverable_branches", [])
        if not isinstance(branches, list) or not all(isinstance(b, str) for b in branches):
            return f"DAG spec node {nid!r}: recoverable_branches must be a list of strings"
        prs = meta.get("linked_open_prs", [])
        if not isinstance(prs, list) or not all(
                isinstance(pr, dict) and isinstance(pr.get("number"), int) and not isinstance(pr.get("number"), bool)
                and isinstance(pr.get("isDraft"), bool) and isinstance(pr.get("url"), (str, type(None))) for pr in prs):
            return f"DAG spec node {nid!r}: linked_open_prs must be a list of {{number, isDraft, url?}}"
    return None


def run_verify(run: Any, ns: argparse.Namespace, command: str) -> None:
    label = STATE["dag_label"]
    raw = None
    try:
        raw = Path(ns.verify_dag).read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError) as exc:  # RecursionError: JSON nested too deeply to parse
        # The receipt names the bytes this run saw: the ones read, or none. Never a later reading.
        if raw is None:
            run.input_unreadable(label, "dag_spec.unreadable")
        else:
            run.input(label, raw)
        run.error("dag_spec.unreadable", f"Cannot read DAG spec: {sanitize_text(str(exc))}", remedy="pass a readable JSON file to --verify-dag",
                  retryable=False, detail={"path": label})
        return
    run.input(label, raw)
    why = check_spec(data)
    if why:
        run.error("dag_spec.invalid", why, remedy="see docs/topics/output for the spec's shape", retryable=False, detail={"path": label})
        return
    merged = {strip_merged_hint(str(m)) for m in data.get("merged", [])}
    result = with_artifact_hash(compile_and_analyze_dag(merged, data.get("nodes", {}), min_confidence=ns.min_confidence))
    failures: list[Failure] = []
    if "cyclic_nodes" in result:
        failures.append(Failure("graph.cycle", result["error"], {"cyclic_nodes": result["cyclic_nodes"]}, "remove an edge of the cycle", False))
    elif not result.get("ok"):
        failures.append(Failure("graph.unresolved_prerequisites", result["error"], {"unknown": len(result.get("unknown_dependencies", [])),
                                "stale_merged_hints": len(result.get("stale_merged_hints", []))}, "fix the references the prerequisite findings name", False))
    emit_plan(run, result, "dag_spec", failures, None, "mermaid" if ns.emit == "mermaid" else None)


def run_inventory(run: Any, ns: argparse.Namespace, command: str) -> None:
    repo = os.path.abspath(ns.repo)
    errors: list[dict[str, str]] = []
    worktrees = collect_worktrees(repo, errors)
    note(f"listed {len(worktrees)} worktree(s)", "git worktree list --porcelain")
    branches = collect_unmerged_branches(repo, errors)
    note(f"listed {len(branches['local'])} local and {len(branches['remote'])} remote unmerged branch(es)", "not merged into origin/main")
    github = collect_github_inventory(repo, ns.milestone, errors)
    snapshot = {"worktrees": worktrees, "unmerged_branches": branches, "github": github}
    run.input(INVENTORY_INPUT, pe.canonical(snapshot))
    counts = {"worktrees": len(worktrees), "local_branches": len(branches["local"]), "remote_branches": len(branches["remote"]),
              "open_prs": len(github["open_prs"]), "open_issues": len(github["open_issues"])}
    run.result({"event": "inventory.summary", "ok": not errors, "milestone": ns.milestone, "counts": counts}, schema_ref("inventory.summary"))
    for w in worktrees:
        run.result({"event": "inventory.worktree", **w}, schema_ref("inventory.worktree"))
    for scope in ("local", "remote"):
        for b in branches[scope]:
            run.result({"event": "inventory.branch", "scope": scope, **b}, schema_ref("inventory.branch"))
    for pr in github["open_prs"]:
        run.result({"event": "inventory.pull_request", **pr}, schema_ref("inventory.pull_request"))
    for i in github["open_issues"]:
        run.result({"event": "inventory.issue", **i}, schema_ref("inventory.issue"))
    for e in errors:
        Failure.from_lookup(e, "inventory").report(run)


# ---- the command line -----------------------------------------------------------------------


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    """argparse that raises instead of printing: a usage error is a Parley startup failure (exit 3)."""

    def error(self, message: str) -> Any:  # type: ignore[override]
        raise UsageError(message)

    def exit(self, status: int = 0, message: str | None = None) -> Any:  # type: ignore[override]
        raise UsageError(message or f"argument parsing ended with status {status}")


def build_parser() -> Parser:
    parser = Parser(prog="taskalisk.py", add_help=False, description="Taskalisk: zero-local-state issue DAG compiler, frontier ranker, and inventory.")
    parser.add_argument("--repo", default=".", help="Path inside the git repository (gh resolves the GitHub repo from it)")
    parser.add_argument("--milestone", default=None, help="Inventory mode only: optional GitHub milestone title filter")
    parser.add_argument("--root", action="append", default=[], help="With --from-github: start discovery at this issue, as owner/repo#N (repeatable)")
    parser.add_argument("--sem-capacity", action="append", default=[], help="Semaphore capacity as name=N (repeatable)")
    parser.add_argument("--compare-relationships", action="store_true")
    parser.add_argument("--from-github", action="store_true")
    parser.add_argument("--verify-dag", default=None)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--emit-mermaid", action="store_true")
    parser.add_argument("--add-edge", default=None)
    parser.add_argument("--remove-edge", default=None)
    parser.add_argument("--reason", default="taskalisk edge update")
    parser.add_argument("--emit-roadmap", action="store_true")
    parser.add_argument("--since-last", action="store_true")
    parser.add_argument("--trust", action="append", default=[], metavar="LOGIN")
    parser.add_argument("--trust-owner", action="append", default=[], metavar="OWNER")
    parser.add_argument("--trust-repo", action="append", default=[], metavar="OWNER/REPO")
    parser.add_argument("--trust-codeowners", action="store_true")
    return parser


def infer_command(args: list[str]) -> list[str]:
    """The 1.x mode flags still select a command, so `--from-github` keeps working: the command is
    put first. An explicit command is left alone, and so is a bare --help or --schema."""
    if args[:1] and args[0] in COMMANDS:
        return list(args)
    # A command named after some flags (`--repo x plan --help`) is the first positional argument;
    # the writer takes the command by position, so it is moved first. A flag's value is never one.
    takes_value = {a for act in build_parser()._actions if act.nargs is None and act.option_strings for a in act.option_strings}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("-"):
            i += 2 if (a in takes_value) else 1
            continue
        if a in COMMANDS:
            return [a, *args[:i], *args[i + 1:]]
        break

    def has(flag: str) -> bool:
        return any(a == flag or a.startswith(flag + "=") for a in args)

    if has("--add-edge") or has("--remove-edge"):
        command = "edit"
    elif has("--from-github"):
        command = "plan"
    elif has("--verify-dag"):
        command = "verify"
    elif any(a in ("--schema", "--help", "-h") for a in args):
        return list(args)
    else:
        command = "inventory"
    return [command, *args]


def resolve(args: list[str], command: str) -> dict[str, Any]:
    """Parse and check the arguments before the bootstrap line, and return the resolved question.
    `question` is what --since-last matches on; it holds no clock, path outside --repo, or secret."""
    ns = build_parser().parse_args(args)
    github = command in ("plan", "edit")
    if command == "edit" and not (ns.add_edge or ns.remove_edge):
        raise UsageError("edit needs --add-edge or --remove-edge")
    if command != "edit" and (ns.add_edge or ns.remove_edge):
        raise UsageError("--add-edge/--remove-edge belong to the edit command (they require --from-github)")
    if ns.add_edge and ns.remove_edge:
        raise UsageError("--add-edge and --remove-edge are mutually exclusive")
    if ns.emit_roadmap and not github:
        raise UsageError("--emit-roadmap requires --from-github")
    if ns.emit_roadmap and ns.emit_mermaid:
        raise UsageError("--emit-roadmap and --emit-mermaid are mutually exclusive")
    if ns.verify_dag and github:
        raise UsageError("--verify-dag and --from-github are mutually exclusive")
    if command == "verify" and not ns.verify_dag:
        raise UsageError("verify needs --verify-dag <file>")
    if parse_capacities(ns.sem_capacity) is None:
        raise UsageError("--sem-capacity takes name=N with N >= 1")
    if (ns.root or ns.compare_relationships or ns.since_last) and not github:
        raise UsageError("--root, --compare-relationships and --since-last require --from-github")
    if (ns.trust or ns.trust_owner or ns.trust_repo or ns.trust_codeowners) and not github:
        raise UsageError("--trust, --trust-owner, --trust-repo and --trust-codeowners require --from-github")
    if any(not OWNER_RE.fullmatch(o) for o in ns.trust_owner) or any(not SLUG_RE.fullmatch(r) for r in ns.trust_repo):
        raise UsageError("--trust-owner takes an owner name; --trust-repo takes owner/repo")
    if ns.emit_mermaid and command == "inventory":
        raise UsageError("--emit-mermaid requires --from-github or --verify-dag")
    # References are part of the argument grammar: a mistaken one did no work, so it fails before the
    # bootstrap line with no receipt (Parley spec 3.2, as decided on flyingrobots/parley#91 and #98).
    for text in ns.root:
        if parse_issue_ref(text) is None:
            raise UsageError(f"--root {text!r} is not a reference (use owner/repo#N; bare numbers are not allowed)")
    edge = ns.add_edge or ns.remove_edge
    if edge:
        parsed = parse_edge_arg(edge)
        if parsed is None:
            raise UsageError(f"Invalid edge syntax (expected 'owner/repo#parent->owner/repo#child'; bare numbers are not allowed): {edge}")
        if parsed[0] == parsed[1]:
            raise UsageError(f"Self-edge rejected: {node_id(*parsed[1])}")
    ns.emit = "roadmap" if ns.emit_roadmap else ("mermaid" if ns.emit_mermaid else None)
    repo = os.path.relpath(os.path.realpath(ns.repo), os.path.realpath(os.getcwd()))
    if github:
        question: dict[str, Any] = {"repo": repo, "roots": sorted(ns.root),
                                    "trust": {"owners": sorted({o.lower() for o in ns.trust_owner}), "repos": sorted({r.lower() for r in ns.trust_repo}),
                                              "logins": sorted({normalize_login(l) for l in ns.trust}), "codeowners": bool(ns.trust_codeowners)}}
        options: dict[str, Any] = {"emit": ns.emit, "compare_relationships": ns.compare_relationships, "since_last": ns.since_last,
                                   "sem_capacity": sorted(ns.sem_capacity)}
        if command == "edit":
            options["edge"] = {"op": "add" if ns.add_edge else "remove", "edge": ns.add_edge or ns.remove_edge, "reason": ns.reason}
    elif command == "verify":
        STATE["dag_label"] = sanitize_home(ns.verify_dag)
        question = {"dag_spec": STATE["dag_label"]}
        options = {"emit": ns.emit, "min_confidence": ns.min_confidence}
    else:
        question = {"repo": repo, "milestone": ns.milestone}
        options = {}
    STATE["ns"], STATE["command"] = ns, command
    STATE["resolved"] = {"command": command, "question": question, "options": options}
    return STATE["resolved"]


def declared_inputs(args: list[str], command: str) -> list[dict[str, Any]]:
    """Each command's one declared input (spec 2.2). Its bytes are supplied once read, so `inv`
    arrives in receipt.inputs: the issues discovery observed, the DAG file, or the inventory."""
    if command in ("plan", "edit"):
        return [{"path": OBSERVATIONS_INPUT, "role": "observations"}]
    if command == "verify":
        return [{"path": STATE["dag_label"], "role": "dag-spec"}]
    return [{"path": INVENTORY_INPUT, "role": "observations"}]


def handler(run: Any, _args: list[str]) -> None:
    global _RUN
    _RUN = run
    command = STATE["command"]
    if STATE.get("inferred"):
        note(f"command {command} inferred from the 1.x mode flags", "no command was named; --add-edge or --remove-edge means edit, --from-github plan, --verify-dag verify, none of them inventory")
    try:
        {"plan": run_plan, "edit": run_plan, "verify": run_verify, "inventory": run_inventory}[command](run, STATE["ns"], command)
    finally:
        _RUN = None


# ---- --human --------------------------------------------------------------------------------

# C0 and C1 controls, line and paragraph separators and bidirectional overrides: none reaches prose.
HUMAN_UNSAFE_RE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")


def hs(value: Any) -> str:
    return HUMAN_UNSAFE_RE.sub(lambda m: "\\u%04x" % ord(m.group()), str(value))


def render_human(line: dict[str, Any]) -> str | None:
    """One line as prose for --human. "" hides a line (the stdout sink drops the empty line);
    None means the writer's default (the bootstrap and a successful end render as nothing)."""
    ev = line.get("event")
    if ev == "plan":
        src = line.get("source") or {}
        out = [f"{hs(src.get('repository') or 'DAG spec')}: {hs(line['outcome'])}"]
        if line["outcome"] == "compiled":
            m = line["metrics"]
            out[0] += (f", {m['open_node_count']} open node(s), {line['open_frontier_count']} on the frontier, a batch of {len(line['batch'])},"
                       f" critical path {m['critical_path_length']}")
        if not line["ok"]:
            out.append(f"NOT OK ({hs(', '.join(line['error_codes']))}): do not dispatch from this plan")
        if line.get("since_last"):
            s = line["since_last"]
            out.append(f"since run {hs(s['compared_with'])}: {s['changes']} change(s)" if s["compared_with"] else "since last: no previous plan of this question")
        if line.get("frontier"):
            out += ["", f"{'rank':>4} {'score':>6}  {'issue':<32} {'status':<12} title"]
        return "\n".join(out)
    if ev == "frontier_node":
        return f"{line['rank']:>4} {line['priority_score']:>6}  {hs(line['id']):<32} {hs(line['status']):<12} {hs(line['title'])}"
    if ev == "batch":
        out = ["", "batch: " + (", ".join(hs(b["id"]) for b in line["members"]) or "(empty)")]
        out += [f"  skipped {hs(s['id'])}: {hs(s['reason'])}" for s in line["skipped"]]
        if line["semaphores_with_unknown_capacity_treated_as_1"]:
            out.append("  unknown capacity, treated as 1: " + ", ".join(hs(n) for n in line["semaphores_with_unknown_capacity_treated_as_1"]))
        return "\n".join(out)
    if ev == "frontier_change":
        return f"{hs(line['change'])}: {hs(line['id'])}"
    if ev in ("node", "wave", "edge"):
        return ""
    if ev == "finding":
        subject = line.get("subject")
        about = f" {hs(subject)}" if subject and subject not in line["message"] else ""
        return f"{hs(line['code'])}{about}: {hs(line['message'])}"
    if ev == "rendering":
        return "\n".join(hs(part) for part in str(line["text"]).split("\n"))
    if ev == "edge_edit":
        state = "dry run, nothing written" if line.get("dry_run") else ("changed" if line["changed"] else "already so, nothing written")
        if "rolled_back" in line:
            state += ", restored" if line["rolled_back"] else ", NOT restored"
        return f"edit {hs(line['type'])} {hs(line['parent'])} -> {hs(line['child'])}: {state}"
    if ev == "inventory.summary":
        c = line["counts"]
        return (f"inventory: {c['worktrees']} worktree(s), {c['local_branches']}+{c['remote_branches']} unmerged branch(es), "
                f"{c['open_prs']} open PR(s), {c['open_issues']} open issue(s)" + ("" if line["ok"] else "; INCOMPLETE, see the errors"))
    if ev == "inventory.worktree":
        dirty = {True: "dirty", False: "clean", None: "unknown"}.get(line.get("dirty"), "unknown")
        return f"worktree {hs(line['path'])} [{hs(line.get('branch', '?'))}] {dirty}"
    if ev == "inventory.branch":
        return f"{hs(line['scope'])} branch {hs(line['branch'])} +{hs(line['ahead_of_main'])}: {hs(line['tip_subject'])}"
    if ev == "inventory.pull_request":
        return f"PR {line.get('number')} {'(draft) ' if line.get('isDraft') else ''}{hs(line.get('title', ''))}"
    if ev == "inventory.issue":
        return f"issue {line['number']} {hs(line['title'])}"
    if ev in ("error", "warning"):
        remedy = f" ({hs(line['remedy'])})" if line.get("remedy") else ""
        return f"{ev} {hs(line['code'])}: {hs(line['problem'])}{remedy}"
    if ev == "command":
        return f"{hs(line['name'])}: {hs(line['intent'])}"
    if ev == "schema":
        return f"schema {hs(line['id'])} {hs(line['version'])}"
    return None


class HumanStdout:
    """Under --human, drop the empty line a hidden record renders to; everything else passes."""

    def __init__(self, inner: Any):
        self.inner = inner

    def write(self, text: str) -> None:
        if text != "\n":
            self.inner.write(text)


PLAN_LINES = ("plan", "frontier_node", "batch", "frontier_change", "node", "wave", "edge", "finding", "rendering")
GITHUB_READS = ["github:issues and their body edit history", "github:pull-requests", "github:collaborator-permissions", "github:CODEOWNERS (--trust-codeowners)", "<repo> git branches"]


def define() -> Any:
    return pe.define_tool(
        name="taskalisk", version=__version__,
        commands={
            "plan": {"intent": "Compile issue-dag/2 frontmatter from GitHub into a reduced DAG, rank the open frontier and propose a conflict-free batch (read-only; --from-github)",
                     "effects": {"reads": GITHUB_READS, "writes": [], "network": True, "idempotent": True},
                     "secrets": SECRETS, "emits": emits(*PLAN_LINES)},
            "edit": {"intent": "Add or remove one edge in a child issue's frontmatter .blocked_by, then recompile; an added edge is restored when the run fails (--add-edge, --remove-edge)",
                     "effects": {"reads": GITHUB_READS, "writes": ["github:issue-body (the child's .blocked_by line)"], "network": True, "idempotent": True},
                     "secrets": SECRETS, "emits": emits("edge_edit", *PLAN_LINES)},
            "verify": {"intent": "Compile a hand-written DAG specification and rank it (read-only; --verify-dag)",
                       "effects": {"reads": ["<the --verify-dag file>"], "writes": [], "network": False, "idempotent": True},
                       "secrets": SECRETS, "emits": emits(*(n for n in PLAN_LINES if n != "frontier_change"))},
            "inventory": {"intent": "List worktrees, unmerged branches, open pull requests and open issues of a repository (read-only, fail-closed). Inventory applies no trust gate: strangers' titles, authors and branch names are listed as data",
                          "effects": {"reads": ["<repo> git worktrees and branches", "github:pull-requests", "github:issues"], "writes": [], "network": True, "idempotent": True},
                          "secrets": SECRETS, "emits": emits("inventory.summary", "inventory.worktree", "inventory.branch", "inventory.pull_request", "inventory.issue")},
        },
        retention={"count": RETENTION},
        human=render_human,
    )


def declaration_unreadable(exc: Exception, human: bool) -> int:
    """Spec 3.2: a run that cannot read its own declaration emits one `startup.failed` line and exits 3.

    The writer starts from the declaration, so it cannot report this one failure itself: the line is
    built here under the writer's own `parley.startup.failed` schema and checked by the writer's
    validator before it is written. Nothing reaches stdout and no receipt is created."""
    name = Path(getattr(exc, "filename", None) or "").name or "a schema file"
    line = {"event": "startup.failed", "t": max(0, int(time.time() * 1000)), "seq": 0, "run": pe.ulid(), "tool": "taskalisk",
            "v": __version__, "code": "startup.declaration_unreadable",
            "problem": f"the declaration could not be read: {name} ({type(exc).__name__})",
            "remedy": "reinstall the skill; its schemas directory is incomplete or damaged",
            "_schema": dict(pe.SCHEMA_IDS["startup_failed"])}
    check = pe.validate_line(line)
    if not check.ok:  # a defect here, not in the installation
        raise RuntimeError(f"startup.failed line does not validate: {check.errors}") from exc
    text = f"startup failed {line['code']}: {line['problem']} ({line['remedy']})" if human else json.dumps(line, separators=(",", ":"), ensure_ascii=False)
    sys.stderr.write(text + "\n")
    sys.stderr.flush()
    return 3


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    args = infer_command(raw)
    STATE.clear()
    STATE["inferred"] = bool(args) and args[0] in COMMANDS and args[0] not in raw
    human = any(a in ("--human", "--humanize") for a in raw)
    try:
        tool = define()
    except (OSError, ValueError) as exc:  # a missing or damaged schema file (json errors are ValueErrors)
        return declaration_unreadable(exc, human)
    return pe.main(tool, ["taskalisk", *args], handler, resolved=resolve, inputs=declared_inputs,
                   stdout=HumanStdout(pe.FdSink(1)) if human else None)


if __name__ == "__main__":
    sys.exit(main())
