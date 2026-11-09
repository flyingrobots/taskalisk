"""Describe per-pass discovery ownership and diagnostic reference sharing."""

from __future__ import annotations

from collections import defaultdict
from typing import TypedDict

from .authorization import TrustPolicy
from .discovery_values import OpaqueIssue, UnmodeledIssue, UntrustedIssue, UntrustedPr
from .frontmatter_values import FrontmatterRecord
from .github_issue_values import IssueMeta
from .graph_values import LinkedPr
from .issue_refs import IssueRef

UNTRUSTED_TITLE = "(untrusted issue)"


class DiscoveryContext(TypedDict):
    """Operator inputs and the shared policy/error channel for one discovery pass."""

    repo: str
    slug: str
    roots: list[str]
    policy: TrustPolicy
    errors: list[dict[str, str]]


class DiscoveryNotes(TypedDict):
    """Diagnostics accumulated before node construction, including excluded inputs."""

    violations: dict[str, list[str]]
    warnings: dict[str, list[str]]
    unmodeled: list[UnmodeledIssue]
    opaque: list[OpaqueIssue]
    untrusted: list[UntrustedIssue]


class IssueClosure(TypedDict):
    """Owned issue evidence; referenced-by lists remain shared with diagnostic entries."""

    seeds: set[IssueRef]
    fetched: dict[IssueRef, IssueMeta]
    records: dict[IssueRef, FrontmatterRecord]
    referenced_by: dict[IssueRef, list[str]]
    notes: DiscoveryNotes


class PrLinks(TypedDict):
    """Admitted task links and the PRs excluded by the same-repository trust rule."""

    by_issue: dict[IssueRef, list[LinkedPr]]
    untrusted: list[UntrustedPr]


def new_closure() -> IssueClosure:
    """Allocate fresh evidence and diagnostics without any process-wide mutable state."""
    return {
        "seeds": set(),
        "fetched": {},
        "records": {},
        "referenced_by": defaultdict(list),
        "notes": {"violations": {}, "warnings": {}, "unmodeled": [], "opaque": [], "untrusted": []},
    }
