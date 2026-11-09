"""Admit the child body for an edge edit without changing mutation authority."""

from __future__ import annotations

from .github import gh_get_issue, gh_issue_edit_history, issue_meta
from .github_issue_values import IssueMeta
from .issue_refs import IssueRef, node_id
from .modes_values import EdgeChange, EditContext


def edge_in_scope(context: EditContext, change: EdgeChange) -> bool:
    """Check both endpoints when adding; removing can repair an out-of-scope parent."""
    parent, child = change["parent"], change["child"]
    for ref in (parent, child) if change["add"] else (child,):
        if not context["policy"].in_scope(ref[0]):
            context["errors"].append(
                {
                    "source": f"edge {node_id(*parent)}->{node_id(*child)}",
                    "error": f"{node_id(*ref)} is outside the trusted repositories",
                }
            )
            return False
    return True


def _admit_body(context: EditContext, child: IssueRef, meta: IssueMeta) -> str | None:
    """Require author then editor trust; any recorded lookup error refuses the edit."""
    policy = context["policy"]
    trusted, reasons = policy.author_trusted(child[0], meta)
    body = meta["body"]
    if trusted:
        history = gh_issue_edit_history(context["repo"], child, context["errors"])
        if history is None:
            return None
        body = history["body"]
        trusted, reasons = policy.editors_trusted(
            child[0], meta.get("author"), history["editors"], meta.get("author_type")
        )
    if context["errors"]:
        return None
    if not trusted:
        context["errors"].append(
            {
                "source": f"frontmatter of {node_id(child[0], child[1], context['home'])}",
                "error": "child is untrusted: " + "; ".join(reasons),
            }
        )
        return None
    return body


def read_child_body(context: EditContext, change: EdgeChange) -> str | None:
    """Read an issue child, refusing PRs before fetching their body edit history."""
    parent, child = change["parent"], change["child"]
    obj = gh_get_issue(context["repo"], child, context["errors"])
    if obj is None:
        return None
    if obj.get("pull_request"):
        context["errors"].append(
            {
                "source": f"edge {node_id(*parent)}->{node_id(*child)}",
                "error": f"{node_id(*child)} is a pull request, not an issue",
            }
        )
        return None
    return _admit_body(context, child, issue_meta(obj))
