"""Select explicitly scoped roots or cache the home repository's open issue seeds."""

from __future__ import annotations

from .discovery_state import DiscoveryContext, IssueClosure, new_closure
from .github import gh_list_open_issues_rest, issue_meta
from .issue_refs import node_id, parse_issue_ref


def collect_seeds(context: DiscoveryContext) -> IssueClosure:
    """Retain REST metadata for author-first admission and refuse invalid explicit roots."""
    closure = new_closure()
    if not context["roots"]:
        for issue in gh_list_open_issues_rest(context["repo"], context["slug"], context["errors"]):
            reference = issue["reference"]
            closure["fetched"][reference] = issue_meta(issue)
            closure["seeds"].add(reference)
        return closure
    for text in context["roots"]:
        reference = parse_issue_ref(text)
        if reference is None:
            context["errors"].append(
                {"source": "--root", "error": f"invalid reference {text!r} (use owner/repo#N)"}
            )
        elif not context["policy"].in_scope(reference[0]):
            context["errors"].append(
                {
                    "source": "--root",
                    "error": f"{node_id(*reference)} is outside the trusted repositories (add --trust-owner or --trust-repo)",
                }
            )
        else:
            closure["seeds"].add(reference)
    return closure
