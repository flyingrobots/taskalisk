"""Validate and publish one edge edit using the existing write/undo contract."""

from __future__ import annotations

from .frontmatter import parse_frontmatter, rewrite_blocked_by, validate_frontmatter
from .github import gh_patch_body
from .issue_refs import node_id
from .modes_admission import edge_in_scope, read_child_body
from .modes_values import EdgeChange, EditContext
from .mutation_values import EdgeUndo


def _edited_body(body: str, context: EditContext, change: EdgeChange) -> str | None:
    """Validate task frontmatter and rewrite only its blocked-by field."""
    parent, child = change["parent"], change["child"]
    source = f"frontmatter of {node_id(child[0], child[1], context['home'])}"
    fields, problems = parse_frontmatter(body)
    if fields is None or problems:
        context["errors"].append({"source": source, "error": "missing or unparseable frontmatter"})
        return None
    record, violations, _ = validate_frontmatter(fields, child)
    if violations or record["kind"] != "task":
        context["errors"].append(
            {
                "source": source,
                "error": "invalid task frontmatter: " + "; ".join(violations or ["not a task"]),
            }
        )
        return None
    refs = list(record["blocked_by"])
    if change["add"] and parent not in refs:
        refs.append(parent)
    if not change["add"]:
        refs = [ref for ref in refs if ref != parent]
    new_body = rewrite_blocked_by(body, refs, child[0])
    if new_body is None:
        context["errors"].append({"source": source, "error": "cannot rewrite .blocked_by"})
    return new_body


def mutate_edge(context: EditContext, change: EdgeChange) -> EdgeUndo | None:
    """Admit, rewrite and patch one child; retain its original body for existing recovery."""
    if not edge_in_scope(context, change):
        return None
    body = read_child_body(context, change)
    if body is None:
        return None
    new_body = _edited_body(body, context, change)
    if new_body is None:
        return None
    if new_body != body and not gh_patch_body(
        context["repo"], change["child"], new_body, context["errors"]
    ):
        return None
    return {"child": change["child"], "old_body": body, "changed": new_body != body}
