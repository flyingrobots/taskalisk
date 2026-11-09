"""Attach authoritative discovery diagnostics to computed graph results."""

from __future__ import annotations

from .discovery import compare_relationships
from .discovery_values import DiscoveryResult, SourceDetails
from .frontmatter import FM_SCHEMA
from .graph import compile_and_analyze_dag
from .graph_results import FrontmatterReport, GraphResult
from .modes_values import PlanOptions


def compile_plan(source: DiscoveryResult, options: PlanOptions) -> GraphResult:
    """Compile the admitted closure and preserve its provenance and format diagnostics."""
    result = compile_and_analyze_dag(
        source["merged"],
        source["nodes"],
        min_confidence=options["min_confidence"],
        capacities=options["capacities"],
    )
    details: SourceDetails = {
        "kind": "issue-frontmatter",
        "schema": FM_SCHEMA,
        "repository": source.get("slug"),
        "roots": options["roots"],
        "trust": source["trust"],
        "containers_excluded": [
            {"id": container["id"], "number": container["number"], "title": container["title"]}
            for container in source["containers"]
        ],
        "unmodeled_open_issues": source["unmodeled_open_issues"],
        "untrusted_issues": source["untrusted_issues"],
        "untrusted_linked_prs": source["untrusted_linked_prs"],
        "opaque_nodes": source["opaque_nodes"],
        "not_planned_parents": source["not_planned_parents"],
    }
    result["source"] = details
    frontmatter: FrontmatterReport = {
        "violating_issues": len(source["violations"]),
        "violations": source["violations"],
        "warnings": source["warnings"],
    }
    result["frontmatter"] = frontmatter
    if source["violations"] and result.get("ok"):
        result["ok"] = False
        result["error"] = f"{len(source['violations'])} issue(s) have invalid frontmatter"
    return result


def compare_plan(repo: str, source: DiscoveryResult, result: GraphResult) -> bool:
    """Attach mirror drift, returning false when lookup failure requires run-error exit 2."""
    errors: list[dict[str, str]] = []
    result["relationship_drift"] = compare_relationships(repo, source, errors)
    if errors:
        result["ok"] = False
        result["error"] = "GitHub relationship lookup failed"
        result["github_errors"] = errors
    return not errors
