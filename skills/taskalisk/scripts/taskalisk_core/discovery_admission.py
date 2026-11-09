"""Enforce repository scope and author-before-editor admission during issue traversal."""

from __future__ import annotations

from enum import Enum, auto

from .discovery_state import DiscoveryContext, IssueClosure
from .github import gh_get_issue, gh_issue_edit_history, issue_meta
from .github_issue_values import IssueMeta
from .issue_refs import IssueRef, node_id


class LookupDecision(Enum):
    """Distinguish a rejected reference from a lookup that stops the whole traversal."""

    SKIP = auto()
    STOP = auto()


def lookup_issue(
    ref: IssueRef, context: DiscoveryContext, closure: IssueClosure
) -> IssueMeta | LookupDecision:
    """Check scope before fetching, preserve seed metadata, and report transferred/PR references."""
    nid = node_id(ref[0], ref[1])
    violations = closure["notes"]["violations"]
    if not context["policy"].in_scope(ref[0]):
        hint = f"add --trust-owner {ref[0].split('/', 1)[0]} or --trust-repo {ref[0]}"
        for source in closure["referenced_by"][ref] or [nid]:
            violations.setdefault(source, []).append(
                f"reference {nid} is outside the trusted repositories; {hint}"
            )
        return LookupDecision.SKIP
    if ref in closure["fetched"]:
        return closure["fetched"][ref]
    issue = gh_get_issue(context["repo"], ref, context["errors"])
    if issue is None:
        return LookupDecision.STOP
    if issue.get("pull_request"):
        violations[nid] = ["references a pull request, not an issue"]
        return LookupDecision.SKIP
    actual = issue["reference"]
    if actual[0].lower() != ref[0].lower() or actual[1] != ref[1]:
        moved = node_id(*actual)
        for source in closure["referenced_by"][ref] or [nid]:
            violations.setdefault(source, []).append(
                f"reference {nid} moved to {moved} (transferred); update the frontmatter"
            )
        return LookupDecision.SKIP
    metadata = issue_meta(issue)
    closure["fetched"][ref] = metadata
    return metadata


def admit_body(
    ref: IssueRef, meta: IssueMeta, context: DiscoveryContext
) -> tuple[bool, list[str]] | None:
    """Check the author first, then bind the body to checked editors; None stops traversal."""
    trusted, reasons = context["policy"].author_trusted(ref[0], meta)
    if trusted:
        history = gh_issue_edit_history(context["repo"], ref, context["errors"])
        if history is None:
            return None
        meta["body"] = history["body"]
        trusted, reasons = context["policy"].editors_trusted(
            ref[0], meta.get("author"), history["editors"], meta.get("author_type")
        )
    return None if context["errors"] else (trusted, reasons)
