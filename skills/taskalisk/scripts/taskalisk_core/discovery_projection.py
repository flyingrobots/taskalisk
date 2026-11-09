"""Project a complete issue closure into task nodes and container/closure diagnostics."""

from __future__ import annotations

from .defaults import PARKED_STATUS
from .discovery_state import UNTRUSTED_TITLE, DiscoveryContext, IssueClosure, PrLinks
from .discovery_values import Container, DiscoveryResult, NotPlannedParent
from .graph_values import Dependency, GraphNode
from .inventory import branches_for_issue
from .issue_refs import IssueRef, node_id


def _dependencies(
    ref: IssueRef, context: DiscoveryContext, closure: IssueClosure
) -> tuple[list[Dependency], list[NotPlannedParent]]:
    """Build task prerequisites and report closed-not-planned parents without leaking titles."""
    nid = node_id(ref[0], ref[1], context["slug"])
    dependencies: list[Dependency] = []
    not_planned: list[NotPlannedParent] = []
    for blocker in closure["records"][ref]["blocked_by"]:
        bid = node_id(blocker[0], blocker[1], context["slug"])
        record = closure["records"].get(blocker)
        if record and record["kind"] == "container":
            closure["notes"]["violations"].setdefault(nid, []).append(
                f".blocked_by names container {bid}"
            )
            continue
        meta = closure["fetched"].get(blocker)
        evidence = f"frontmatter: {nid} .blocked_by {bid}"
        if meta is not None and meta["state"] == "closed" and meta["state_reason"] == "not_planned":
            title = UNTRUSTED_TITLE if (record or {}).get("untrusted") else meta["title"]
            not_planned.append({"parent": bid, "child": nid, "title": title})
        dependencies.append(
            {
                "from": bid,
                "type": "frontmatter",
                "isHard": True,
                "confidence": 1.0,
                "evidence": evidence,
            }
        )
    return dependencies, not_planned


def _task_node(
    ref: IssueRef,
    context: DiscoveryContext,
    closure: IssueClosure,
    links: PrLinks,
    branches: list[str],
) -> tuple[GraphNode, list[NotPlannedParent]]:
    """Return a task node and its closure notices, retaining existing status precedence."""
    record = closure["records"][ref]
    meta = closure["fetched"][ref]
    dependencies, not_planned = _dependencies(ref, context, closure)
    untrusted = bool(record.get("untrusted"))
    linked = links["by_issue"].get(ref, []) if ref[0] == context["slug"] and not untrusted else []
    status = record["status"] or "open"
    if linked:
        status = "in-review" if any(not pr["isDraft"] for pr in linked) else "wip"
    elif status == "active":
        status = "in-progress"
    elif status == "parked":
        status = PARKED_STATUS
    node: GraphNode = {
        "title": UNTRUSTED_TITLE if untrusted else meta["title"],
        "type": record["type"] or ("opaque" if record["kind"] == "opaque" else "task"),
        "workstream": record["type"] or "unassigned",
        "status": status,
        "depends_on": dependencies,
        "holds": record["holds"],
        "meters": record["meters"],
        "size_hours": record["size_hours"],
        "linked_open_prs": linked,
        "recoverable_branches": branches_for_issue(ref[1], branches)
        if ref[0] == context["slug"]
        else [],
        "url": meta["html_url"],
        "opaque": record["kind"] == "opaque",
        "untrusted": untrusted,
    }
    return node, not_planned


def project_closure(
    context: DiscoveryContext, closure: IssueClosure, links: PrLinks, branches: list[str]
) -> DiscoveryResult:
    """Publish a complete closure while retaining diagnostic and evidence insertion order."""
    merged: set[str] = set()
    nodes: dict[str, GraphNode] = {}
    containers: list[Container] = []
    not_planned: list[NotPlannedParent] = []
    for ref, record in closure["records"].items():
        nid = node_id(ref[0], ref[1], context["slug"])
        meta = closure["fetched"][ref]
        if record["kind"] == "container":
            containers.append(
                {
                    "id": nid,
                    "number": ref[1],
                    "title": meta["title"],
                    "children": [
                        node_id(child[0], child[1], context["slug"]) for child in record["children"]
                    ],
                }
            )
        elif meta["state"] == "closed":
            merged.add(nid)
        else:
            node, notices = _task_node(ref, context, closure, links, branches)
            nodes[nid] = node
            not_planned.extend(notices)
    notes = closure["notes"]
    return {
        "merged": merged,
        "nodes": nodes,
        "containers": containers,
        "slug": context["slug"],
        "violations": notes["violations"],
        "warnings": notes["warnings"],
        "unmodeled_open_issues": notes["unmodeled"],
        "opaque_nodes": notes["opaque"],
        "not_planned_parents": not_planned,
        "records": closure["records"],
        "fetched": closure["fetched"],
        "untrusted_issues": notes["untrusted"],
        "untrusted_linked_prs": links["untrusted"],
        "trust": context["policy"].describe(),
    }
