"""Translate operator edge requests and retain the existing rollback sequencing."""

from __future__ import annotations

from .authorization import TrustPolicy
from .authorization_values import TrustOptions
from .github import gh_patch_body, gh_repo_slug
from .issue_refs import node_id, parse_edge_arg
from .modes_mutation import mutate_edge
from .modes_values import EdgeRequest, EditContext, EditOutcome
from .mutation_values import EdgeMutation
from .output import write_json


def apply_edge(
    repo: str, request: EdgeRequest, trust: TrustOptions, errors: list[dict[str, str]]
) -> EditOutcome | int:
    """Return admitted edit evidence or emit the original structured failure and exit code."""
    parsed = parse_edge_arg(request["text"])
    if parsed is None:
        write_json(
            {
                "ok": False,
                "error": f"Invalid edge syntax (expected 'owner/repo#parent->owner/repo#child'; bare numbers are not allowed): {request['text']}",
            },
            indent=None,
        )
        return 1
    slug = gh_repo_slug(repo, errors)
    if slug is None:
        write_json({"ok": False, "error": "GitHub mutation failed", "github_errors": errors})
        return 2
    parent, child = parsed
    if parent == child:
        write_json(
            {"ok": False, "error": f"Self-edge rejected: {node_id(child[0], child[1], slug)}"},
            indent=None,
        )
        return 1
    context: EditContext = {
        "repo": repo,
        "home": slug,
        "policy": TrustPolicy(repo, slug, trust, errors),
        "errors": errors,
    }
    undo = mutate_edge(context, {"parent": parent, "child": child, "add": request["add"]})
    if undo is None:
        write_json({"ok": False, "error": "Frontmatter edit failed", "github_errors": errors})
        return 2 if any(error["source"].startswith("gh ") for error in errors) else 1
    child_id = node_id(child[0], child[1], slug)
    mutation: EdgeMutation = {
        "type": "add_blocked_by" if request["add"] else "remove_blocked_by",
        "parent": node_id(parent[0], parent[1], slug),
        "child": child_id,
        "changed": undo["changed"],
        "reason": request["reason"],
        "recorded_in": f"frontmatter of {child_id} (the issue edit history is the ledger)",
    }
    return {"mutation": mutation, "undo": undo}


def rollback_failed_add(repo: str, outcome: EditOutcome | None) -> None:
    """Restore a changed added edge after failure; issue #1 owns optimistic recovery changes."""
    if outcome is None:
        return
    mutation, undo = outcome["mutation"], outcome["undo"]
    if mutation["type"] != "add_blocked_by" or not undo["changed"]:
        return
    errors: list[dict[str, str]] = []
    mutation["rolled_back"] = gh_patch_body(repo, undo["child"], undo["old_body"], errors)
    if errors:
        mutation["rollback_errors"] = errors
