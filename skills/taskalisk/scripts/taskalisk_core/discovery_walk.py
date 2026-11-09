"""Traverse admitted issue references while preserving opaque and excluded evidence."""

from __future__ import annotations

from collections import deque
from itertools import chain

from .discovery_admission import LookupDecision, admit_body, lookup_issue
from .discovery_state import DiscoveryContext, IssueClosure
from .frontmatter import parse_frontmatter, validate_frontmatter
from .frontmatter_values import FrontmatterRecord
from .github_issue_values import IssueMeta
from .issue_refs import IssueRef, node_id


def _record_untrusted(
    ref: IssueRef,
    meta: IssueMeta,
    reasons: list[str],
    closure: IssueClosure,
) -> None:
    """Retain an opaque blocker and shared references, without any untrusted title or metadata."""
    nid = node_id(ref[0], ref[1])
    closure["notes"]["untrusted"].append(
        {
            "id": nid,
            "url": meta["html_url"],
            "state": meta["state"],
            "author": meta.get("author"),
            "reasons": reasons,
            "referenced_by": closure["referenced_by"][ref],
        }
    )
    closure["records"][ref] = {
        "kind": "opaque",
        "untrusted": True,
        "blocked_by": [],
        "children": [],
        "holds": [],
        "meters": [],
        "status": "blocked",
        "size_hours": None,
        "type": None,
    }


def _unmodeled_record(
    ref: IssueRef, meta: IssueMeta, context: DiscoveryContext, closure: IssueClosure
) -> FrontmatterRecord | None:
    """List unmodeled home seeds; other missing models remain opaque blockers."""
    nid = node_id(ref[0], ref[1])
    if ref in closure["seeds"] and not context["roots"]:
        closure["notes"]["unmodeled"].append(
            {"id": nid, "title": meta["title"], "url": meta["html_url"]}
        )
        return None
    closure["notes"]["opaque"].append(
        {
            "id": nid,
            "title": meta["title"],
            "state": meta["state"],
            "referenced_by": closure["referenced_by"][ref],
        }
    )
    return {
        "kind": "opaque",
        "blocked_by": [],
        "children": [],
        "holds": [],
        "meters": [],
        "status": "blocked",
        "size_hours": None,
        "type": None,
    }


def _read_model(
    ref: IssueRef, meta: IssueMeta, context: DiscoveryContext, closure: IssueClosure
) -> FrontmatterRecord | None:
    """Parse only an admitted body and retain format diagnostics alongside its model."""
    fields, problems = parse_frontmatter(meta["body"])
    if fields is None:
        return _unmodeled_record(ref, meta, context, closure)
    record, violations, warnings = validate_frontmatter(fields, ref)
    violations = problems + violations
    nid = node_id(ref[0], ref[1])
    if violations:
        closure["notes"]["violations"][nid] = violations
    if warnings:
        closure["notes"]["warnings"][nid] = warnings
    return record


def _visit_issue(
    ref: IssueRef, context: DiscoveryContext, closure: IssueClosure, queue: deque[IssueRef]
) -> bool:
    """Visit one reference; false stops traversal without querying the next queued issue."""
    meta = lookup_issue(ref, context, closure)
    if isinstance(meta, LookupDecision):
        return meta is LookupDecision.SKIP
    admission = admit_body(ref, meta, context)
    if admission is None:
        return False
    trusted, reasons = admission
    if not trusted:
        _record_untrusted(ref, meta, reasons, closure)
        return True
    record = _read_model(ref, meta, context, closure)
    if record is not None:
        closure["records"][ref] = record
        nid = node_id(ref[0], ref[1])
        for dependency in chain(record["children"], record["blocked_by"]):
            closure["referenced_by"][dependency].append(nid)
            queue.append(dependency)
    return True


def walk_closure(context: DiscoveryContext, closure: IssueClosure) -> None:
    """Traverse sorted seeds once, then drop only unreferenced untrusted seed records."""
    queue = deque(sorted(closure["seeds"]))
    seen: set[IssueRef] = set()
    while queue:
        reference = queue.popleft()
        if reference in seen:
            continue
        seen.add(reference)
        if not _visit_issue(reference, context, closure, queue):
            break
    if context["errors"]:
        return
    for reference in [
        ref
        for ref, record in closure["records"].items()
        if record.get("untrusted")
        and ref in closure["seeds"]
        and not closure["referenced_by"].get(ref)
    ]:
        del closure["records"][reference]
