"""Parse and format repository-qualified issue identities."""

from __future__ import annotations

import re

IssueRef = tuple[str, int]  # (owner/repo slug, issue number)

ISSUE_REF_RE = re.compile(r"\s*(?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<num>[1-9][0-9]*)\s*")

REPOSITORY_URL_RE = re.compile(r"/repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/?$")


def node_id(slug: str, number: int, home: str = "") -> str:
    """Format a qualified 'owner/repo#123' identity.

    Bare references could silently change meaning after an issue transfer.
    """
    return f"{slug}#{number}"


def parse_issue_ref(text: str, home: str = "") -> IssueRef | None:
    """Parse 'owner/repo#123'. A bare '#123' or '123' is invalid."""
    m = ISSUE_REF_RE.fullmatch(text)
    if not m:
        return None
    # GitHub owner and repository names are case-insensitive; one canonical spelling per issue.
    return (m.group("slug").lower(), int(m.group("num")))


def parse_edge_arg(arg: str, home: str = "") -> tuple[IssueRef, IssueRef] | None:
    """'owner/repo#1080->owner/repo#1052' means the first blocks the second (parent -> child)."""
    parts = arg.split("->")
    if len(parts) != 2:
        return None
    parent, child = parse_issue_ref(parts[0]), parse_issue_ref(parts[1])
    if parent is None or child is None:
        return None
    return parent, child


def slug_from_repository_url(url: str) -> str | None:
    """Extract and case-fold a repository identity from a REST repository URL."""
    m = REPOSITORY_URL_RE.search(url or "")
    return m.group(1).lower() if m else None


def id_sort_key(nid: str) -> tuple[str, int]:
    """Sort by repository slug, then by number."""
    slug, _, num = nid.rpartition("#")
    return (slug, int(num) if num.isdigit() else 0)


def format_ref_relative(ref: IssueRef, base_slug: str = "") -> str:
    """Always the qualified form; the name is kept for call sites."""
    return f"{ref[0]}#{ref[1]}"
