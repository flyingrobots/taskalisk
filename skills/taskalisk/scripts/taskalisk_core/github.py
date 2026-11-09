"""Adapt GitHub CLI issue, PR and edit-history reads and writes."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from .defaults import GH_ISSUE_LIST_LIMIT, GH_PR_LIST_LIMIT
from .issue_refs import IssueRef, node_id
from .process import (
    parse_json,
    parse_json_list,
    parse_paginated_arrays,
    run_cmd_checked,
    sanitize_home,
)


def gh_list_open_prs(repo: str, errors: list[dict[str, str]]) -> list[dict[str, Any]]:
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
    return prs


def gh_list_open_issues(
    repo: str, milestone: str | None, errors: list[dict[str, str]]
) -> list[dict[str, Any]]:
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
    return issues


# --------------------------------------------------------------------------- #
# GitHub-native DAG source
# --------------------------------------------------------------------------- #


def gh_repo_slug(repo: str, errors: list[dict[str, str]]) -> str | None:
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
) -> list[dict[str, Any]]:
    """Return the issues that block `number`, via GitHub's native dependency API."""
    source = f"gh api repos/{slug}/issues/{number}/dependencies/blocked_by"
    ok, raw, err = run_cmd_checked(
        ["gh", "api", "--paginate", f"repos/{slug}/issues/{number}/dependencies/blocked_by"],
        cwd=repo,
    )
    if not ok:
        errors.append({"source": source, "error": err or "command failed"})
        return []
    return parse_paginated_arrays(raw, source, errors)


def gh_list_open_issues_rest(
    repo: str, slug: str, errors: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Open issues of `slug` with author login, actor type and association, so the trust gate
    can reject a stranger's issue before any further query (C1, C15). Pull requests are dropped."""
    source = f"gh api repos/{slug}/issues"
    ok, raw, err = run_cmd_checked(
        ["gh", "api", "--paginate", f"repos/{slug}/issues?state=open&per_page=100"], cwd=repo
    )
    if not ok:
        errors.append({"source": source, "error": err or "command failed"})
        return []
    items = [
        it
        for it in parse_paginated_arrays(raw, source, errors)
        if isinstance(it, dict) and not it.get("pull_request")
    ]
    if len(items) >= GH_ISSUE_LIST_LIMIT:
        errors.append(
            {
                "source": source,
                "error": f"Result reached {GH_ISSUE_LIST_LIMIT} issues; refusing a possibly truncated seed set",
            }
        )
    return items


def issue_meta(obj: dict[str, Any]) -> dict[str, Any]:
    """The fields discovery keeps from a REST issue object."""
    user = obj.get("user") or {}
    return {
        "title": obj.get("title", ""),
        "state": str(obj.get("state", "open")).lower(),
        "state_reason": obj.get("state_reason"),
        "body": obj.get("body") or "",
        "html_url": obj.get("html_url"),
        "author": user.get("login"),
        "author_type": user.get("type"),
        "association": obj.get("author_association"),
    }


def gh_issue_database_id(
    repo: str, slug: str, number: int, errors: list[dict[str, str]]
) -> int | None:
    ok, raw, err = run_cmd_checked(
        ["gh", "api", f"repos/{slug}/issues/{number}", "--jq", ".id"], cwd=repo
    )
    if not ok or not raw:
        errors.append(
            {"source": f"gh api repos/{slug}/issues/{number}", "error": err or "command failed"}
        )
        return None
    return int(raw)


def gh_get_issue(repo: str, ref: IssueRef, errors: list[dict[str, str]]) -> dict[str, Any] | None:
    ok, raw, err = run_cmd_checked(["gh", "api", f"repos/{ref[0]}/issues/{ref[1]}"], cwd=repo)
    if not ok:
        errors.append(
            {"source": f"gh api repos/{ref[0]}/issues/{ref[1]}", "error": err or "command failed"}
        )
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
        proc = subprocess.run(
            ["gh", "api", "-X", "PATCH", f"repos/{ref[0]}/issues/{ref[1]}", "--input", "-"],
            cwd=repo,
            input=json.dumps({"body": body}),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except (FileNotFoundError, PermissionError) as exc:
        errors.append(
            {
                "source": f"gh api PATCH repos/{ref[0]}/issues/{ref[1]}",
                "error": sanitize_home(str(exc)),
            }
        )
        return False
    if proc.returncode != 0:
        errors.append(
            {
                "source": f"gh api PATCH repos/{ref[0]}/issues/{ref[1]}",
                "error": sanitize_home(proc.stderr.strip()) or "command failed",
            }
        )
        return False
    return True


# The body and the actor of every body edit (the first edit is the creation), in one
# query, so the editors checked are the editors of the body that is parsed.
EDIT_HISTORY_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!,$after:String){"
    "repository(owner:$owner,name:$name){issue(number:$number){body "
    "userContentEdits(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{editor{login __typename}}}}}}"
)


def gh_issue_edit_history(
    repo: str, ref: IssueRef, errors: list[dict[str, str]]
) -> dict[str, Any] | None:
    """The current body and every body editor of an issue: {"body": str, "editors": [{"login", "type"}]}.
    Every page is read; a page that claims a next page without a cursor fails the lookup (exit 2)."""
    owner, name = ref[0].split("/", 1)
    source = f"gh api graphql (edit history of {node_id(*ref)})"
    editors: list[dict[str, Any]] = []
    body: str | None = None
    after: str | None = None
    while True:
        cmd = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={EDIT_HISTORY_QUERY}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={ref[1]}",
        ]
        if after:
            cmd += ["-f", f"after={after}"]
        ok, raw, err = run_cmd_checked(cmd, cwd=repo)
        if not ok:
            errors.append({"source": source, "error": err or "command failed"})
            return None
        data = parse_json(raw, source, errors)
        issue = (
            (((data or {}).get("data") or {}).get("repository") or {}).get("issue")
            if isinstance(data, dict)
            else None
        )
        if not isinstance(issue, dict):
            errors.append({"source": source, "error": "GraphQL response has no issue"})
            return None
        if body is None:
            body = issue.get("body") or ""
        edits = issue.get("userContentEdits")
        if not isinstance(edits, dict) or not isinstance(edits.get("nodes"), list):
            # A missing connection is not "no editors"; it is an answer we cannot read.
            errors.append(
                {
                    "source": source,
                    "error": "GraphQL response has no readable userContentEdits connection",
                }
            )
            return None
        for node in edits["nodes"]:
            editor = (node or {}).get("editor") or {}
            editors.append({"login": editor.get("login"), "type": editor.get("__typename")})
        page = edits.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return {"body": body, "editors": editors}
        if not page.get("endCursor"):
            errors.append(
                {
                    "source": source,
                    "error": "edit history reports another page but no cursor; refusing a partial editor list",
                }
            )
            return None
        after = str(page["endCursor"])
