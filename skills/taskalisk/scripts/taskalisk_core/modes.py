"""Coordinate specification, GitHub compilation and edge-edit modes."""

from __future__ import annotations

import json

from .authorization import TrustPolicy
from .authorization_values import TrustOptions
from .discovery import collect_frontmatter_dag, compare_relationships
from .discovery_values import SourceDetails
from .frontmatter import FM_SCHEMA, parse_frontmatter, rewrite_blocked_by, validate_frontmatter
from .github import gh_get_issue, gh_issue_edit_history, gh_patch_body, gh_repo_slug, issue_meta
from .graph import compile_and_analyze_dag
from .graph_results import FrontmatterReport
from .issue_refs import IssueRef, node_id, parse_edge_arg
from .mutation_values import EdgeMutation, EdgeUndo
from .output import emit, with_artifact_hash
from .process import sanitize_home
from .spec_file import read_spec

# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #


def verify_and_layer_dag(dag_path: str, min_confidence: float, emit_mermaid: bool) -> int:
    """Validate a bounded local spec, then emit its plan or structured refusal."""
    try:
        data = read_spec(dag_path)
    except (OSError, TypeError, ValueError) as exc:
        print(
            json.dumps({"ok": False, "error": f"Cannot read DAG spec: {sanitize_home(str(exc))}"})
        )
        return 1
    result = compile_and_analyze_dag(data["merged"], data["nodes"], min_confidence=min_confidence)
    return emit(with_artifact_hash(result), emit_mermaid)


def mutate_edge(
    repo: str,
    home: str,
    parent: IssueRef,
    child: IssueRef,
    add: bool,
    errors: list[dict[str, str]],
    policy: TrustPolicy,
) -> EdgeUndo | None:
    """Edit the child's frontmatter .blocked_by. Returns {"child": ref, "old_body": str} or None."""
    # The child is always checked. The parent's scope matters only when an edge is added:
    # removing a reference to an out-of-scope issue is how an operator repairs such a reference.
    for ref in (parent, child) if add else (child,):
        if not policy.in_scope(ref[0]):
            errors.append(
                {
                    "source": f"edge {node_id(*parent)}->{node_id(*child)}",
                    "error": f"{node_id(*ref)} is outside the trusted repositories",
                }
            )
            return None
    obj = gh_get_issue(repo, child, errors)
    if obj is None:
        return None
    if obj.get("pull_request"):
        errors.append(
            {
                "source": f"edge {node_id(*parent)}->{node_id(*child)}",
                "error": f"{node_id(*child)} is a pull request, not an issue",
            }
        )
        return None
    meta = issue_meta(obj)
    trusted, reasons = policy.author_trusted(child[0], meta)
    body = meta["body"]
    if trusted:
        history = gh_issue_edit_history(repo, child, errors)
        if history is None:
            return None
        body = history["body"]
        trusted, reasons = policy.editors_trusted(
            child[0], meta.get("author"), history["editors"], meta.get("author_type")
        )
    if errors:
        # A trust lookup that recorded an error (for example a failed CODEOWNERS fetch) never permits a write.
        return None
    if not trusted:
        # Never write into a stranger's issue, even with the permission to do so (C3).
        errors.append(
            {
                "source": f"frontmatter of {node_id(child[0], child[1], home)}",
                "error": "child is untrusted: " + "; ".join(reasons),
            }
        )
        return None
    fields, problems = parse_frontmatter(body)
    if fields is None or problems:
        errors.append(
            {
                "source": f"frontmatter of {node_id(child[0], child[1], home)}",
                "error": "missing or unparseable frontmatter",
            }
        )
        return None
    record, violations, _ = validate_frontmatter(fields, child)
    if violations or record["kind"] != "task":
        errors.append(
            {
                "source": f"frontmatter of {node_id(child[0], child[1], home)}",
                "error": "invalid task frontmatter: " + "; ".join(violations or ["not a task"]),
            }
        )
        return None
    refs = list(record["blocked_by"])
    if add and parent not in refs:
        refs.append(parent)
    if not add:
        refs = [r for r in refs if r != parent]
    new_body = rewrite_blocked_by(body, refs, child[0])
    if new_body is None:
        errors.append(
            {
                "source": f"frontmatter of {node_id(child[0], child[1], home)}",
                "error": "cannot rewrite .blocked_by",
            }
        )
        return None
    if new_body != body and not gh_patch_body(repo, child, new_body, errors):
        return None
    return {"child": child, "old_body": body, "changed": new_body != body}


def compile_from_github(
    repo: str,
    roots: list[str],
    min_confidence: float,
    emit_mermaid: bool,
    add_edge: str | None,
    remove_edge: str | None,
    reason: str,
    emit_roadmap: bool = False,
    capacities: dict[str, int] | None = None,
    compare: bool = False,
    trust: TrustOptions | None = None,
) -> int:
    """Compile trusted issue closure and optionally edit one frontmatter edge."""
    errors: list[dict[str, str]] = []
    mutation: EdgeMutation | None = None
    undo: EdgeUndo | None = None
    trust = trust or {}

    if add_edge or remove_edge:
        if parse_edge_arg(add_edge or remove_edge or "") is None:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"Invalid edge syntax (expected 'owner/repo#parent->owner/repo#child'; bare numbers are not allowed): {add_edge or remove_edge}",
                    }
                )
            )
            return 1
        slug = gh_repo_slug(repo, errors)
        if slug is None:
            print(
                json.dumps(
                    {"ok": False, "error": "GitHub mutation failed", "github_errors": errors},
                    indent=2,
                )
            )
            return 2
        parsed = parse_edge_arg(add_edge or remove_edge or "", slug)
        assert parsed is not None
        parent, child = parsed
        if parent == child:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"Self-edge rejected: {node_id(child[0], child[1], slug)}",
                    }
                )
            )
            return 1
        policy = TrustPolicy(
            repo,
            slug,
            trust.get("owners", []),
            trust.get("repos", []),
            trust.get("logins", []),
            bool(trust.get("codeowners")),
            errors,
        )
        undo = mutate_edge(
            repo, slug, parent, child, add=bool(add_edge), errors=errors, policy=policy
        )
        if undo is None:
            print(
                json.dumps(
                    {"ok": False, "error": "Frontmatter edit failed", "github_errors": errors},
                    indent=2,
                )
            )
            return 2 if any(e["source"].startswith("gh ") for e in errors) else 1
        child_id = node_id(child[0], child[1], slug)
        mutation = {
            "type": "add_blocked_by" if add_edge else "remove_blocked_by",
            "parent": node_id(parent[0], parent[1], slug),
            "child": child_id,
            "changed": undo["changed"],
            "reason": reason,
            "recorded_in": f"frontmatter of {child_id} (the issue edit history is the ledger)",
        }

    source = collect_frontmatter_dag(repo, roots, errors, trust)
    if errors or "trust" not in source:
        if mutation and mutation["type"] == "add_blocked_by" and undo and undo["changed"]:
            # The recompile that would have caught a cycle did not run; do not leave the unchecked edge on GitHub.
            rb_errors: list[dict[str, str]] = []
            mutation["rolled_back"] = gh_patch_body(
                repo, undo["child"], undo["old_body"], rb_errors
            )
            if rb_errors:
                mutation["rollback_errors"] = rb_errors
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "GitHub inventory failed; refusing to compile a partial graph",
                    "github_errors": errors,
                    "mutation": mutation,
                },
                indent=2,
            )
        )
        return 2

    result = compile_and_analyze_dag(
        source["merged"], source["nodes"], min_confidence=min_confidence, capacities=capacities
    )
    details: SourceDetails = {
        "kind": "issue-frontmatter",
        "schema": FM_SCHEMA,
        "repository": source.get("slug"),
        "roots": roots,
        "trust": source["trust"],
        "containers_excluded": [
            {"id": c["id"], "number": c["number"], "title": c["title"]}
            for c in source["containers"]
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
    rel_errors: list[dict[str, str]] = []
    if compare:
        result["relationship_drift"] = compare_relationships(repo, source, rel_errors)
    if rel_errors:
        # A failed gh call is never an empty drift report (doctrine 4); the run fails below, after any rollback.
        result["ok"] = False
        result["error"] = "GitHub relationship lookup failed"
        result["github_errors"] = rel_errors
    if mutation:
        result["mutation"] = mutation

    if (
        not result.get("ok")
        and mutation
        and mutation["type"] == "add_blocked_by"
        and undo
        and undo["changed"]
    ):
        # Restore the child's body so a cycle never persists in the truth source, whatever made the run fail.
        rb_errors: list[dict[str, str]] = []
        mutation["rolled_back"] = gh_patch_body(repo, undo["child"], undo["old_body"], rb_errors)
        if rb_errors:
            mutation["rollback_errors"] = rb_errors

    code = emit(with_artifact_hash(result), emit_mermaid, emit_roadmap)
    return 2 if rel_errors else code
