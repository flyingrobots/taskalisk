"""Coordinate local verification, GitHub discovery, optional edits and rendering."""

from __future__ import annotations

from .authorization_values import TrustOptions
from .discovery import collect_frontmatter_dag
from .graph import compile_and_analyze_dag
from .modes_edit import apply_edge, rollback_failed_add
from .modes_results import compare_plan, compile_plan
from .modes_values import EdgeRequest, EditOutcome, PlanOptions
from .output import OutputView, emit, with_artifact_hash, write_json
from .process import sanitize_home
from .spec_file import read_spec


def verify_and_layer_dag(dag_path: str, min_confidence: float, view: OutputView) -> int:
    """Validate a bounded local spec, then emit its plan or structured refusal."""
    try:
        data = read_spec(dag_path)
    except (OSError, TypeError, ValueError) as exc:
        write_json(
            {"ok": False, "error": f"Cannot read DAG spec: {sanitize_home(str(exc))}"}, indent=None
        )
        return 1
    result = compile_and_analyze_dag(data["merged"], data["nodes"], min_confidence=min_confidence)
    return emit(with_artifact_hash(result), view)


def compile_from_github(
    repo: str,
    options: PlanOptions,
    view: OutputView,
    trust: TrustOptions,
    edit: EdgeRequest | None,
) -> int:
    """Sequence the existing edit, discovery, analysis, comparison and recovery operations."""
    errors: list[dict[str, str]] = []
    outcome: EditOutcome | None = None
    if edit is not None:
        attempt = apply_edge(repo, edit, trust, errors)
        if isinstance(attempt, int):
            return attempt
        outcome = attempt
    source = collect_frontmatter_dag(repo, options["roots"], errors, trust)
    if errors or "trust" not in source:
        rollback_failed_add(repo, outcome)
        write_json(
            {
                "ok": False,
                "error": "GitHub inventory failed; refusing to compile a partial graph",
                "github_errors": errors,
                "mutation": outcome["mutation"] if outcome else None,
            }
        )
        return 2
    result = compile_plan(source, options)
    comparison_ok = compare_plan(repo, source, result) if options["compare"] else True
    if outcome:
        result["mutation"] = outcome["mutation"]
    if not result.get("ok"):
        rollback_failed_add(repo, outcome)
    code = emit(with_artifact_hash(result), view)
    return code if comparison_ok else 2
