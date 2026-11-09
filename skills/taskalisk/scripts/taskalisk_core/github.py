"""Adapt GitHub CLI issue, PR and edit-history reads and writes."""

from __future__ import annotations

import json

from .defaults import GH_ISSUE_LIST_LIMIT, GH_PR_LIST_LIMIT
from .github_history import gh_issue_edit_history as gh_issue_edit_history
from .github_inventory_values import InventoryIssue, parse_inventory_issue
from .github_issue_values import IssueMeta, RestIssue, parse_rest_issue
from .github_json import (
    parse_json,
    parse_json_list,
    parse_paginated_arrays,
)
from .github_pr_values import PullRequest, parse_pull_request
from .issue_refs import IssueRef
from .process import run_cmd_checked


def gh_list_open_prs(repo: str, errors: list[dict[str, str]]) -> list[PullRequest]:
    """Return a complete checked PR inventory or a structured run error."""
    cmd = [
        "gh",
        "pr",
        "list",
        "--state",
        "open",
        "--limit",
        str(GH_PR_LIST_LIMIT),
        # author and isCrossRepository feed the PR trust check (C4); without them every PR is untrusted.
        "--json",
        "number,title,headRefName,isDraft,url,closingIssuesReferences,author,isCrossRepository",
    ]
    ok, raw, err = run_cmd_checked(cmd, cwd=repo)
    if not ok:
        errors.append({"source": "gh pr list", "error": err or "command failed"})
        return []
    prs = parse_json_list(raw, "gh pr list", errors)
    if len(prs) >= GH_PR_LIST_LIMIT:
        errors.append(
            {
                "source": "gh pr list",
                "error": f"Result filled --limit {GH_PR_LIST_LIMIT}; possible truncation",
            }
        )
    if errors:
        return []
    try:
        return [parse_pull_request(pr) for pr in prs]
    except (TypeError, ValueError) as exc:
        errors.append({"source": "gh pr list", "error": str(exc)})
        return []


def gh_list_open_issues(
    repo: str, milestone: str | None, errors: list[dict[str, str]]
) -> list[InventoryIssue]:
    """Summarize all checked CLI issue rows or report a complete-inventory failure."""
    cmd = [
        "gh",
        "issue",
        "list",
        "--state",
        "open",
        "--limit",
        str(GH_ISSUE_LIST_LIMIT),
        "--json",
        "number,title,labels,milestone,url,body",
    ]
    if milestone:
        cmd.extend(["--milestone", milestone])
    ok, raw, err = run_cmd_checked(cmd, cwd=repo)
    if not ok:
        errors.append({"source": "gh issue list", "error": err or "command failed"})
        return []
    issues = parse_json_list(raw, "gh issue list", errors)
    if len(issues) >= GH_ISSUE_LIST_LIMIT:
        errors.append(
            {
                "source": "gh issue list",
                "error": f"Result filled --limit {GH_ISSUE_LIST_LIMIT}; possible truncation",
            }
        )
    if errors:
        return []
    try:
        return [parse_inventory_issue(issue) for issue in issues]
    except (TypeError, ValueError) as exc:
        errors.append({"source": "gh issue list", "error": str(exc)})
        return []


# --------------------------------------------------------------------------- #
# GitHub-native DAG source
# --------------------------------------------------------------------------- #


def gh_repo_slug(repo: str, errors: list[dict[str, str]]) -> str | None:
    """Read the repository identity selected by the local checkout."""
    ok, raw, err = run_cmd_checked(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=repo
    )
    if not ok or not raw:
        errors.append({"source": "gh repo view", "error": err or "command failed"})
        return None
    # The same canonical spelling as parsed references (parse_issue_ref), or the home issues never match their own .id.
    return raw.lower()


def gh_blocked_by(
    repo: str, slug: str, number: int, errors: list[dict[str, str]]
) -> list[RestIssue]:
    """Return the issues that block `number`, via GitHub's native dependency API."""
    source = f"gh api repos/{slug}/issues/{number}/dependencies/blocked_by"
    ok, raw, err = run_cmd_checked(
        ["gh", "api", "--paginate", f"repos/{slug}/issues/{number}/dependencies/blocked_by"],
        cwd=repo,
    )
    if not ok:
        errors.append({"source": source, "error": err or "command failed"})
        return []
    return _rest_issues(raw, source, errors)


def _rest_issues(raw: str, source: str, errors: list[dict[str, str]]) -> list[RestIssue]:
    """Admit every consumed row, or return no rows and a source-qualified run error."""
    rows = parse_paginated_arrays(raw, source, errors)
    if errors:
        return []
    try:
        return [parse_rest_issue(row) for row in rows]
    except (TypeError, ValueError) as exc:
        errors.append({"source": source, "error": str(exc)})
        return []


def gh_list_open_issues_rest(repo: str, slug: str, errors: list[dict[str, str]]) -> list[RestIssue]:
    """Read open issues with author evidence before further trust queries.

    Drop PR rows and expose login, actor type and association for C1 and C15.
    """
    source = f"gh api repos/{slug}/issues"
    ok, raw, err = run_cmd_checked(
        ["gh", "api", "--paginate", f"repos/{slug}/issues?state=open&per_page=100"], cwd=repo
    )
    if not ok:
        errors.append({"source": source, "error": err or "command failed"})
        return []
    rows = _rest_issues(raw, source, errors)
    if any(row["reference"][0] != slug.lower() for row in rows):
        errors.append({"source": source, "error": "issue listing returned a different repository"})
        return []
    items = [row for row in rows if not row["pull_request"]]
    if len(items) >= GH_ISSUE_LIST_LIMIT:
        errors.append(
            {
                "source": source,
                "error": f"Result reached {GH_ISSUE_LIST_LIMIT} issues; refusing a possibly truncated seed set",
            }
        )
    return items


def issue_meta(obj: RestIssue) -> IssueMeta:
    """The checked fields discovery keeps from a REST issue object."""
    return obj["meta"]


def gh_issue_database_id(
    repo: str, slug: str, number: int, errors: list[dict[str, str]]
) -> int | None:
    """Read an issue database ID, recording command or conversion failures."""
    ok, raw, err = run_cmd_checked(
        ["gh", "api", f"repos/{slug}/issues/{number}", "--jq", ".id"], cwd=repo
    )
    if not ok or not raw:
        errors.append(
            {"source": f"gh api repos/{slug}/issues/{number}", "error": err or "command failed"}
        )
        return None
    return int(raw)


def gh_get_issue(repo: str, ref: IssueRef, errors: list[dict[str, str]]) -> RestIssue | None:
    """Admit a complete issue or report a structured transport/field failure."""
    ok, raw, err = run_cmd_checked(["gh", "api", f"repos/{ref[0]}/issues/{ref[1]}"], cwd=repo)
    if not ok:
        errors.append(
            {"source": f"gh api repos/{ref[0]}/issues/{ref[1]}", "error": err or "command failed"}
        )
        return None
    source = f"gh api repos/{ref[0]}/issues/{ref[1]}"
    obj = parse_json(raw, source, errors)
    if any(e["source"] == source for e in errors):
        return None
    try:
        return parse_rest_issue(obj)
    except (TypeError, ValueError) as exc:
        errors.append({"source": source, "error": str(exc)})
        return None


def gh_patch_body(repo: str, ref: IssueRef, body: str, errors: list[dict[str, str]]) -> bool:
    """Attempt one bounded PATCH; a failed command does not prove no remote effect."""
    ok, _, error = run_cmd_checked(
        ["gh", "api", "-X", "PATCH", f"repos/{ref[0]}/issues/{ref[1]}", "--input", "-"],
        cwd=repo,
        input_text=json.dumps({"body": body}),
    )
    if not ok:
        errors.append(
            {
                "source": f"gh api PATCH repos/{ref[0]}/issues/{ref[1]}",
                "error": error or "command failed",
            }
        )
        return False
    return True
