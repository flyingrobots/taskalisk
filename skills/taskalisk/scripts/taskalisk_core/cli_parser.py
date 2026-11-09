"""Declare the public argparse contract and its typed destination attributes."""

from __future__ import annotations

import argparse

from .defaults import DEFAULT_MIN_CONFIDENCE


class ParsedArgs(argparse.Namespace):
    """Attributes populated by this module's fixed parser declarations, before any use."""

    repo: str
    milestone: str | None
    root: list[str]
    sem_capacity: list[str]
    compare_relationships: bool
    from_github: bool
    verify_dag: str | None
    min_confidence: float
    emit_mermaid: bool
    add_edge: str | None
    remove_edge: str | None
    reason: str
    emit_roadmap: bool
    trust: list[str]
    trust_owner: list[str]
    trust_repo: list[str]
    trust_codeowners: bool


def build_parser() -> argparse.ArgumentParser:
    """Keep option declarations, order, defaults, help and argparse conversion together."""
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
    return parser
