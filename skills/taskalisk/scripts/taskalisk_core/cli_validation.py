"""Validate operator option combinations before provider calls or remote effects."""

from __future__ import annotations

import argparse

from .cli_parser import ParsedArgs, build_parser
from .identities import OWNER_RE, SLUG_RE


def parse_capacities(items: list[str]) -> dict[str, int] | None:
    """Parse positive name=count capacities, refusing any malformed item."""
    caps: dict[str, int] = {}
    for item in items:
        name, _, num = item.partition("=")
        if not name or not num.isdigit() or int(num) < 1:
            return None
        caps[name] = int(num)
    return caps


def _validate_modes(parser: argparse.ArgumentParser, args: ParsedArgs) -> None:
    """Preserve the first four mode conflict checks and their diagnostic precedence."""
    if (args.add_edge or args.remove_edge) and not args.from_github:
        parser.error("--add-edge/--remove-edge require --from-github")
    if args.add_edge and args.remove_edge:
        parser.error("--add-edge and --remove-edge are mutually exclusive")
    if args.emit_roadmap and not args.from_github:
        parser.error("--emit-roadmap requires --from-github")
    if args.verify_dag and args.from_github:
        parser.error("--verify-dag and --from-github are mutually exclusive")


def _validate_scope_options(parser: argparse.ArgumentParser, args: ParsedArgs) -> None:
    """Validate GitHub-only options and repository scope spelling after capacities."""
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


def parse_options() -> tuple[ParsedArgs, dict[str, int]]:
    """Populate the declared namespace and refuse invalid options before dispatch."""
    parser = build_parser()
    args = ParsedArgs()
    parser.parse_args(namespace=args)
    _validate_modes(parser, args)
    capacities = parse_capacities(args.sem_capacity)
    if capacities is None:
        parser.error("--sem-capacity takes name=N with N >= 1")
    _validate_scope_options(parser, args)
    return args, capacities
