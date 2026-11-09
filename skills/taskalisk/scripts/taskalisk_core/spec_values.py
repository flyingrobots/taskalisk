"""Admit consumed local DAG fields before the graph compiler sees them."""

from __future__ import annotations

from . import spec_checks as check
from .frontmatter_values import Meter
from .graph_dependencies import strip_merged_hint
from .graph_values import DagSpec, DependencyEntry, GraphNode, LinkedPr


def _dependency(value: object) -> DependencyEntry:
    """Preserve textual references and fill checked object defaults."""
    if isinstance(value, str):
        return check.identifier(value, "dependency")
    row = check.fields(value, "dependency")
    return {
        "from": check.identifier(row.get("from"), "dependency from"),
        "type": check.text(row.get("type", "accepted"), "dependency type"),
        "isHard": check.boolean(row.get("isHard", True), "isHard"),
        "confidence": check.confidence(row.get("confidence", 1.0)),
        "evidence": check.text(row.get("evidence", "Declared in DAG specification"), "evidence"),
    }


def _meter(value: object) -> Meter:
    """Admit a named semaphore with a positive integral slot request."""
    row = check.fields(value, "meter")
    return {
        "name": check.identifier(row.get("name"), "meter name"),
        "slots": check.positive_integer(row.get("slots"), "meter slots"),
    }


def _linked_pr(value: object) -> LinkedPr:
    """Check a local display summary without claiming GitHub author trust."""
    row = check.fields(value, "linked PR")
    return {
        "number": check.positive_integer(row.get("number"), "linked PR number"),
        "isDraft": check.boolean(row.get("isDraft", False), "linked PR isDraft"),
        "url": check.nullable_text(row.get("url"), "linked PR url"),
    }


def _node(value: object, name: str) -> GraphNode:
    """Normalize aliases and defaults only after validating consumed values."""
    row = check.fields(value, f"node {name}")
    deps = row.get("depends_on", row.get("prerequisites", []))
    holds = row.get("holds", row.get("resources", []))
    meters = row.get("meters", [])
    size = row.get("size_hours")
    return {
        "title": check.text(row.get("title", ""), "title"),
        "url": check.nullable_text(row.get("url"), "url"),
        "milestone": check.nullable_text(row.get("milestone"), "milestone"),
        "in_filter": check.boolean(row.get("in_filter", True), "in_filter"),
        "type": check.text(row.get("type", ""), "type"),
        "workstream": check.text(row.get("workstream", ""), "workstream"),
        "status": check.text(row.get("status", "open"), "status"),
        "size_hours": None if size is None else check.positive_integer(size, "size_hours"),
        "depends_on": [_dependency(item) for item in check.array(deps, "depends_on")],
        "holds": [] if holds is None else check.identifiers(holds, "holds"),
        "meters": []
        if meters is None
        else [_meter(item) for item in check.array(meters, "meters")],
        "linked_open_prs": [
            _linked_pr(item)
            for item in check.array(row.get("linked_open_prs", []), "linked_open_prs")
        ],
        "recoverable_branches": check.identifiers(
            row.get("recoverable_branches", []), "recoverable_branches"
        ),
        "opaque": check.boolean(row.get("opaque", False), "opaque"),
        "untrusted": check.boolean(row.get("untrusted", False), "untrusted"),
    }


def parse_spec(value: object) -> DagSpec:
    """Admit all nodes or raise; no partial graph escapes a malformed spec."""
    root = check.fields(value, "DAG spec")
    nodes = check.fields(root.get("nodes", {}), "nodes")
    merged = check.identifiers(root.get("merged", []), "merged")
    return {
        "merged": {strip_merged_hint(item) for item in merged},
        "nodes": {check.identifier(key, "node ID"): _node(row, key) for key, row in nodes.items()},
    }
