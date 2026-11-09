"""Discover trusted issue closure and compare relationship mirrors."""

from __future__ import annotations

from collections import defaultdict, deque

from .authorization import TrustPolicy
from .authorization_values import TrustOptions
from .defaults import PARKED_STATUS
from .discovery_values import (
    Container,
    Discovery,
    DiscoveryFailure,
    DiscoveryResult,
    NotPlannedParent,
    OpaqueIssue,
    RelationshipDrift,
    UnmodeledIssue,
    UntrustedIssue,
    UntrustedPr,
)
from .frontmatter import parse_frontmatter, validate_frontmatter
from .frontmatter_values import FrontmatterRecord
from .github import (
    gh_blocked_by,
    gh_get_issue,
    gh_issue_edit_history,
    gh_list_open_issues_rest,
    gh_list_open_prs,
    gh_repo_slug,
    issue_meta,
)
from .github_issue_values import IssueMeta
from .graph_values import Dependency, GraphNode, LinkedPr
from .inventory import branches_for_issue, list_branches
from .issue_refs import IssueRef, node_id, parse_issue_ref

UNTRUSTED_TITLE = "(untrusted issue)"


def collect_frontmatter_dag(
    repo: str, roots: list[str], errors: list[dict[str, str]], trust: TrustOptions | None = None
) -> Discovery:
    """Build (merged, nodes) from issue frontmatter, across repositories."""
    empty: DiscoveryFailure = {"merged": set(), "nodes": {}, "containers": [], "slug": None}
    slug = gh_repo_slug(repo, errors)
    if slug is None:
        return empty
    trust = trust or {}
    policy = TrustPolicy(
        repo,
        slug,
        trust.get("owners", []),
        trust.get("repos", []),
        trust.get("logins", []),
        bool(trust.get("codeowners")),
        errors,
    )
    prs = gh_list_open_prs(repo, errors)
    branches = list_branches(repo, errors)
    fetched: dict[IssueRef, IssueMeta] = {}
    queue: deque[IssueRef] = deque()
    seeds: set[IssueRef] = set()
    if roots:
        for text in roots:
            r = parse_issue_ref(text)
            if r is None:
                errors.append(
                    {"source": "--root", "error": f"invalid reference {text!r} (use owner/repo#N)"}
                )
            elif not policy.in_scope(r[0]):
                errors.append(
                    {
                        "source": "--root",
                        "error": f"{node_id(*r)} is outside the trusted repositories (add --trust-owner or --trust-repo)",
                    }
                )
            else:
                seeds.add(r)
    else:
        for iss in gh_list_open_issues_rest(repo, slug, errors):
            r = iss["reference"]
            fetched[r] = issue_meta(iss)
            seeds.add(r)
    if errors:
        return empty
    queue.extend(sorted(seeds))

    # A PR links a task only from a same-repository branch by a trusted author (C4).
    prs_by_issue: dict[IssueRef, list[LinkedPr]] = defaultdict(list)
    untrusted_prs: list[UntrustedPr] = []
    for pr in prs:
        closes = pr["closes"]
        if not closes:
            continue
        identity = pr["author"]
        author = identity["login"] if identity else None
        cross = pr["cross_repository"]
        ok, why = (
            (False, "head is not a branch of this repository")
            if cross is not False
            else policy.login_trusted(slug, author, None, identity["type"] if identity else None)
        )
        if errors:
            return empty
        if not ok:
            untrusted_prs.append(
                {
                    "number": pr.get("number"),
                    "url": pr.get("url"),
                    "author": author,
                    "cross_repository": cross,
                    "closes": [node_id(*c) for c in closes],
                    "reason": why,
                }
            )
            continue
        for c in closes:
            prs_by_issue[c].append(
                {"number": pr["number"], "isDraft": pr["isDraft"], "url": pr.get("url")}
            )

    seen: set[IssueRef] = set()
    referenced_by: dict[IssueRef, list[str]] = defaultdict(list)
    records: dict[IssueRef, FrontmatterRecord] = {}
    violations: dict[str, list[str]] = {}
    warnings: dict[str, list[str]] = {}
    unmodeled_seeds: list[UnmodeledIssue] = []
    untrusted: list[UntrustedIssue] = []
    opaque: list[OpaqueIssue] = []
    containers: list[Container] = []
    not_planned: list[NotPlannedParent] = []
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
                violations.setdefault(who, []).append(
                    f"reference {nid} is outside the trusted repositories; {hint}"
                )
            continue
        if ref not in fetched:
            obj = gh_get_issue(repo, ref, errors)
            if obj is None:
                break
            if obj.get("pull_request"):
                violations[nid] = ["references a pull request, not an issue"]
                continue
            actual = obj["reference"]
            if actual[0].lower() != ref[0].lower() or actual[1] != ref[1]:
                moved = node_id(*actual)
                for who in referenced_by[ref] or [nid]:
                    violations.setdefault(who, []).append(
                        f"reference {nid} moved to {moved} (transferred); update the frontmatter"
                    )
                continue
            fetched[ref] = issue_meta(obj)
        meta = fetched[ref]
        # Author first, from the REST object: a stranger's issue costs no further query (C1, C15).
        trusted, reasons = policy.author_trusted(ref[0], meta)
        if trusted:
            history = gh_issue_edit_history(repo, ref, errors)
            if history is None:
                break
            meta["body"] = history["body"]  # the body whose editors were checked
            trusted, reasons = policy.editors_trusted(
                ref[0], meta.get("author"), history["editors"], meta.get("author_type")
            )
        if errors:
            break
        if not trusted:
            # No title: nothing an untrusted author wrote reaches any output (C3).
            untrusted.append(
                {
                    "id": nid,
                    "url": meta["html_url"],
                    "state": meta["state"],
                    "author": meta.get("author"),
                    "reasons": reasons,
                    "referenced_by": referenced_by[ref],
                }
            )
            # Always an opaque record: a trusted issue that references it must stay blocked (C3).
            # Unreferenced untrusted seeds are dropped after discovery, below.
            records[ref] = {
                "kind": "opaque",
                "untrusted": True,
                "blocked_by": [],
                "children": [],
                "holds": [],
                "meters": [],
                "status": "blocked",
                "size_hours": None,
                "type": None,
            }
            continue
        fields, problems = parse_frontmatter(meta["body"])
        if fields is None:
            if ref in seeds and not roots:
                unmodeled_seeds.append({"id": nid, "title": meta["title"], "url": meta["html_url"]})
            else:
                opaque.append(
                    {
                        "id": nid,
                        "title": meta["title"],
                        "state": meta["state"],
                        "referenced_by": referenced_by[ref],
                    }
                )
                records[ref] = {
                    "kind": "opaque",
                    "blocked_by": [],
                    "children": [],
                    "holds": [],
                    "meters": [],
                    "status": "blocked",
                    "size_hours": None,
                    "type": None,
                }
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
    for ref in [
        r
        for r, rec in records.items()
        if rec.get("untrusted") and r in seeds and not referenced_by.get(r)
    ]:
        del records[ref]

    merged: set[str] = set()
    nodes: dict[str, GraphNode] = {}
    for ref, rec in records.items():
        nid = node_id(ref[0], ref[1], slug)
        meta = fetched[ref]
        if rec["kind"] == "container":
            containers.append(
                {
                    "id": nid,
                    "number": ref[1],
                    "title": meta["title"],
                    "children": [node_id(c[0], c[1], slug) for c in rec["children"]],
                }
            )
            continue
        if meta["state"] == "closed":
            merged.add(nid)
            continue
        depends_on: list[Dependency] = []
        for blk in rec["blocked_by"]:
            bid = node_id(blk[0], blk[1], slug)
            brec = records.get(blk)
            if brec and brec["kind"] == "container":
                violations.setdefault(nid, []).append(f".blocked_by names container {bid}")
                continue
            bmeta = fetched.get(blk)
            evidence = f"frontmatter: {nid} .blocked_by {bid}"
            if (
                bmeta is not None
                and bmeta["state"] == "closed"
                and bmeta["state_reason"] == "not_planned"
            ):
                # A closed untrusted blocker still contributes no title (C3).
                btitle = UNTRUSTED_TITLE if (brec or {}).get("untrusted") else bmeta["title"]
                not_planned.append({"parent": bid, "child": nid, "title": btitle})
            depends_on.append(
                {
                    "from": bid,
                    "type": "frontmatter",
                    "isHard": True,
                    "confidence": 1.0,
                    "evidence": evidence,
                }
            )
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
            "title": UNTRUSTED_TITLE if untrusted_node else meta["title"],
            "type": rec["type"] or ("opaque" if rec["kind"] == "opaque" else "task"),
            "workstream": rec["type"] or "unassigned",
            "status": status,
            "depends_on": depends_on,
            "holds": rec["holds"],
            "meters": rec["meters"],
            "size_hours": rec["size_hours"],
            "linked_open_prs": linked,
            "recoverable_branches": branches_for_issue(ref[1], branches) if ref[0] == slug else [],
            "url": meta["html_url"],
            "opaque": rec["kind"] == "opaque",
            "untrusted": untrusted_node,
        }
    return {
        "merged": merged,
        "nodes": nodes,
        "containers": containers,
        "slug": slug,
        "violations": violations,
        "warnings": warnings,
        "unmodeled_open_issues": unmodeled_seeds,
        "opaque_nodes": opaque,
        "not_planned_parents": not_planned,
        "records": records,
        "fetched": fetched,
        "untrusted_issues": untrusted,
        "untrusted_linked_prs": untrusted_prs,
        "trust": policy.describe(),
    }


def compare_relationships(
    repo: str, source: DiscoveryResult, errors: list[dict[str, str]]
) -> RelationshipDrift:
    """Drift between frontmatter edges and GitHub blocked_by relationships (a mirror)."""
    slug = source["slug"]
    only_fm: list[str] = []
    only_gh: list[str] = []
    for ref, rec in source["records"].items():
        if rec["kind"] != "task" or source["fetched"][ref]["state"] == "closed":
            continue
        nid = node_id(ref[0], ref[1], slug)
        gh_set = {blk["reference"] for blk in gh_blocked_by(repo, ref[0], ref[1], errors)}
        fm_set = set(rec["blocked_by"])
        only_fm += [f"{node_id(b[0], b[1], slug)} -> {nid}" for b in sorted(fm_set - gh_set)]
        only_gh += [f"{node_id(b[0], b[1], slug)} -> {nid}" for b in sorted(gh_set - fm_set)]
    return {
        "only_in_frontmatter": only_fm,
        "only_in_github": only_gh,
        "in_sync": not only_fm and not only_gh,
    }
