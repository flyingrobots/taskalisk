"""Route validated operator options to inventory, local verification or GitHub planning."""

from __future__ import annotations

import os

from .authorization_values import TrustOptions
from .cli_parser import ParsedArgs
from .cli_validation import parse_options
from .inventory import collect_github_inventory, collect_unmerged_branches, collect_worktrees
from .modes import compile_from_github, verify_and_layer_dag
from .modes_values import EdgeRequest, PlanOptions
from .output import OutputView, write_json


def _view(args: ParsedArgs) -> OutputView:
    """Retain roadmap precedence when both existing rendering flags are present."""
    if args.emit_roadmap:
        return OutputView.ROADMAP
    return OutputView.MERMAID if args.emit_mermaid else OutputView.JSON


def _github(repo: str, args: ParsedArgs, capacities: dict[str, int], view: OutputView) -> int:
    """Build cohesive planning, trust and optional edge-edit inputs from parsed flags."""
    options: PlanOptions = {
        "roots": args.root,
        "min_confidence": args.min_confidence,
        "capacities": capacities,
        "compare": args.compare_relationships,
    }
    trust: TrustOptions = {
        "owners": args.trust_owner,
        "repos": args.trust_repo,
        "logins": args.trust,
        "codeowners": args.trust_codeowners,
    }
    edit: EdgeRequest | None = None
    if args.add_edge or args.remove_edge:
        edit = {
            "text": args.add_edge or args.remove_edge or "",
            "add": bool(args.add_edge),
            "reason": args.reason,
        }
    return compile_from_github(repo, options, view, trust, edit)


def _inventory(repo: str, milestone: str | None) -> int:
    """Emit the complete inventory or its original partial snapshot with run-error exit 2."""
    errors: list[dict[str, str]] = []
    snapshot = {
        "ok": True,
        "worktrees": collect_worktrees(repo, errors),
        "unmerged_branches": collect_unmerged_branches(repo, errors),
        "github": collect_github_inventory(repo, milestone, errors),
        "inventory_errors": errors,
    }
    if errors:
        snapshot["ok"] = False
    write_json(snapshot)
    return 2 if errors else 0


def main() -> int:
    """Parse, validate and dispatch without performing effects during option admission."""
    args, capacities = parse_options()
    repo = os.path.abspath(args.repo)
    view = _view(args)
    if args.from_github:
        return _github(repo, args, capacities, view)
    if args.verify_dag:
        return verify_and_layer_dag(args.verify_dag, args.min_confidence, view)
    return _inventory(repo, args.milestone)
