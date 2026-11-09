"""Coordinate trusted issue discovery and compare authoritative edges with mirrors."""

from __future__ import annotations

from .authorization import TrustPolicy
from .authorization_values import TrustOptions
from .discovery_projection import project_closure
from .discovery_prs import collect_pr_links
from .discovery_seeds import collect_seeds
from .discovery_state import DiscoveryContext
from .discovery_values import Discovery, DiscoveryFailure, DiscoveryResult, RelationshipDrift
from .discovery_walk import walk_closure
from .github import gh_blocked_by, gh_list_open_prs, gh_repo_slug
from .inventory import list_branches
from .issue_refs import node_id


def collect_frontmatter_dag(
    repo: str, roots: list[str], errors: list[dict[str, str]], trust: TrustOptions | None = None
) -> Discovery:
    """Build a complete admitted closure without changing provider or diagnostic order."""
    empty: DiscoveryFailure = {"merged": set(), "nodes": {}, "containers": [], "slug": None}
    slug = gh_repo_slug(repo, errors)
    if slug is None:
        return empty
    trust = trust or {}
    policy = TrustPolicy(repo, slug, trust, errors)
    context: DiscoveryContext = {
        "repo": repo,
        "slug": slug,
        "roots": roots,
        "policy": policy,
        "errors": errors,
    }
    prs = gh_list_open_prs(repo, errors)
    branches = list_branches(repo, errors)
    closure = collect_seeds(context)
    if errors:
        return empty
    links = collect_pr_links(context, prs)
    if errors:
        return empty
    walk_closure(context, closure)
    if errors:
        return empty
    return project_closure(context, closure, links, branches)


def compare_relationships(
    repo: str, source: DiscoveryResult, errors: list[dict[str, str]]
) -> RelationshipDrift:
    """Drift between frontmatter edges and GitHub blocked_by relationships (a mirror)."""
    only_fm: list[str] = []
    only_gh: list[str] = []
    for ref, rec in source["records"].items():
        if rec["kind"] != "task" or source["fetched"][ref]["state"] == "closed":
            continue
        nid = node_id(ref[0], ref[1])
        gh_set = {blk["reference"] for blk in gh_blocked_by(repo, ref[0], ref[1], errors)}
        fm_set = set(rec["blocked_by"])
        only_fm += [f"{node_id(b[0], b[1])} -> {nid}" for b in sorted(fm_set - gh_set)]
        only_gh += [f"{node_id(b[0], b[1])} -> {nid}" for b in sorted(gh_set - fm_set)]
    return {
        "only_in_frontmatter": only_fm,
        "only_in_github": only_gh,
        "in_sync": not only_fm and not only_gh,
    }
