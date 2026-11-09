"""Parse and route the public command-line interface."""

from __future__ import annotations

import argparse
import json
import os

from .defaults import DEFAULT_MIN_CONFIDENCE
from .identities import OWNER_RE, SLUG_RE
from .inventory import collect_github_inventory, collect_unmerged_branches, collect_worktrees
from .modes import compile_from_github, verify_and_layer_dag


def parse_capacities(items: list[str]) -> dict[str, int] | None:
    caps: dict[str, int] = {}
    for item in items:
        name, _, num = item.partition("=")
        if not name or not num.isdigit() or int(num) < 1:
            return None
        caps[name] = int(num)
    return caps


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Taskalisk: zero-local-state issue DAG compiler, frontier ranker, and inventory."
    )
    parser.add_argument(
        "--repo",
        default=".",
        help="Path inside the git repository (gh resolves the GitHub repo from it)",
    )
    parser.add_argument(
        "--milestone",
        default=None,
        help="Inventory mode only: optional GitHub milestone title filter",
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="With --from-github: start discovery at this issue, as owner/repo#N (repeatable); default is every open home issue",
    )
    parser.add_argument(
        "--sem-capacity",
        action="append",
        default=[],
        help="Semaphore capacity as name=N (repeatable); unknown semaphores count as 1",
    )
    parser.add_argument(
        "--compare-relationships",
        action="store_true",
        help="With --from-github: report drift between frontmatter edges and GitHub blocked_by relationships",
    )
    parser.add_argument(
        "--from-github",
        action="store_true",
        help="Compile the DAG from issue frontmatter (issue-dag/2), across repositories",
    )
    parser.add_argument(
        "--verify-dag",
        default=None,
        help="Path to a hand-written DAG JSON specification to verify and layer",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=DEFAULT_MIN_CONFIDENCE,
        help=f"Minimum confidence for hard edges in --verify-dag specs (default {DEFAULT_MIN_CONFIDENCE})",
    )
    parser.add_argument(
        "--emit-mermaid",
        action="store_true",
        help="Output a transitively-reduced Mermaid flowchart TD",
    )
    parser.add_argument(
        "--add-edge",
        default=None,
        help="Add 'owner/repo#parent->owner/repo#child' to the child's frontmatter .blocked_by, then recompile (rolls back on cycle).",
    )
    parser.add_argument(
        "--remove-edge",
        default=None,
        help="Remove 'owner/repo#parent->owner/repo#child' from the child's frontmatter .blocked_by, then recompile.",
    )
    parser.add_argument(
        "--reason",
        default="taskalisk edge update",
        help="Rationale echoed in the output for the mutation (GitHub timeline is the ledger)",
    )
    parser.add_argument(
        "--emit-roadmap",
        action="store_true",
        help="With --from-github: print the generated ROADMAP.md block (between BEGIN/END markers)",
    )
    parser.add_argument(
        "--trust",
        action="append",
        default=[],
        metavar="LOGIN",
        help="With --from-github: a login trusted as author or editor everywhere (repeatable)",
    )
    parser.add_argument(
        "--trust-owner",
        action="append",
        default=[],
        metavar="OWNER",
        help="With --from-github: add every repository of this owner to the trusted scope (repeatable; the home owner is always in scope)",
    )
    parser.add_argument(
        "--trust-repo",
        action="append",
        default=[],
        metavar="OWNER/REPO",
        help="With --from-github: add one repository to the trusted scope (repeatable)",
    )
    parser.add_argument(
        "--trust-codeowners",
        action="store_true",
        help="With --from-github: trust the logins named in each scope repository's CODEOWNERS on its default branch",
    )
    args = parser.parse_args()

    if (args.add_edge or args.remove_edge) and not args.from_github:
        parser.error("--add-edge/--remove-edge require --from-github")
    if args.add_edge and args.remove_edge:
        parser.error("--add-edge and --remove-edge are mutually exclusive")
    if args.emit_roadmap and not args.from_github:
        parser.error("--emit-roadmap requires --from-github")
    if args.verify_dag and args.from_github:
        parser.error("--verify-dag and --from-github are mutually exclusive")

    capacities = parse_capacities(args.sem_capacity)
    if capacities is None:
        parser.error("--sem-capacity takes name=N with N >= 1")
    if (args.root or args.compare_relationships) and not args.from_github:
        parser.error("--root and --compare-relationships require --from-github")
    trust_flags = args.trust or args.trust_owner or args.trust_repo or args.trust_codeowners
    if trust_flags and not args.from_github:
        parser.error(
            "--trust, --trust-owner, --trust-repo and --trust-codeowners require --from-github"
        )
    if any(not OWNER_RE.fullmatch(o) for o in args.trust_owner) or any(
        not SLUG_RE.fullmatch(r) for r in args.trust_repo
    ):
        parser.error("--trust-owner takes an owner name; --trust-repo takes owner/repo")
    trust = {
        "owners": args.trust_owner,
        "repos": args.trust_repo,
        "logins": args.trust,
        "codeowners": args.trust_codeowners,
    }

    repo = os.path.abspath(args.repo)
    if args.from_github:
        return compile_from_github(
            repo,
            args.root,
            args.min_confidence,
            args.emit_mermaid,
            args.add_edge,
            args.remove_edge,
            args.reason,
            emit_roadmap=args.emit_roadmap,
            capacities=capacities,
            compare=args.compare_relationships,
            trust=trust,
        )
    if args.verify_dag:
        return verify_and_layer_dag(args.verify_dag, args.min_confidence, args.emit_mermaid)

    errors: list[dict[str, str]] = []
    snapshot = {
        "ok": True,
        "worktrees": collect_worktrees(repo, errors),
        "unmerged_branches": collect_unmerged_branches(repo, errors),
        "github": collect_github_inventory(repo, args.milestone, errors),
        "inventory_errors": errors,
    }
    if errors:
        snapshot["ok"] = False
        print(json.dumps(snapshot, indent=2))
        return 2
    print(json.dumps(snapshot, indent=2))
    return 0
