"""Admit task links only from trusted authors on same-repository PR branches."""

from __future__ import annotations

from collections import defaultdict

from .discovery_state import DiscoveryContext, PrLinks
from .github_pr_values import PullRequest
from .issue_refs import node_id


def collect_pr_links(context: DiscoveryContext, prs: list[PullRequest]) -> PrLinks:
    """Preserve PR order and stop immediately when an author lookup records a run error."""
    links: PrLinks = {"by_issue": defaultdict(list), "untrusted": []}
    for pr in prs:
        closes = pr["closes"]
        if not closes:
            continue
        identity = pr["author"]
        author = identity["login"] if identity else None
        cross = pr["cross_repository"]
        trusted, reason = (
            (False, "head is not a branch of this repository")
            if cross is not False
            else context["policy"].login_trusted(
                context["slug"], author, None, identity["type"] if identity else None
            )
        )
        if context["errors"]:
            return links
        if not trusted:
            links["untrusted"].append(
                {
                    "number": pr.get("number"),
                    "url": pr.get("url"),
                    "author": author,
                    "cross_repository": cross,
                    "closes": [node_id(*reference) for reference in closes],
                    "reason": reason,
                }
            )
            continue
        for reference in closes:
            links["by_issue"][reference].append(
                {"number": pr["number"], "isDraft": pr["isDraft"], "url": pr.get("url")}
            )
    return links
