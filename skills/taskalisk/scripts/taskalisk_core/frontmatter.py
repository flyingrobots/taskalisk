"""Parse, validate and rewrite the issue-dag frontmatter format."""

from __future__ import annotations

import re
from typing import Any

from .issue_refs import IssueRef, format_ref_relative, node_id, parse_issue_ref

# --------------------------------------------------------------------------- #
# Frontmatter model (issue-dag/2). See docs/frontmatter-model.md.
# --------------------------------------------------------------------------- #

FM_SCHEMA = "issue-dag/2"

FM_RETIRED_SCHEMAS = {
    "issue-dag/1": "issue-dag/1 allowed repository-relative references; rewrite every reference as owner/repo#N and set .dag: issue-dag/2"
}

FM_PREFIX = "."

FM_KEYS = {
    ".dag",
    ".id",
    ".kind",
    ".type",
    ".blocked_by",
    ".children",
    ".size_hours",
    ".holds",
    ".meters",
    ".status",
}

FM_KINDS = {"task", "container"}

FM_TYPES = {"feature", "bug", "decision", "research", "investigation", "spike", "task"}

FM_STATUSES = {"active", "parked", "blocked"}

FM_SIZE_WARN_HOURS = 8

FM_BLOCK_RE = re.compile(r"\A\s*```yaml[ \t]*\r?\n(?P<yaml>.*?)\r?\n```[ \t]*(?:\r?\n|\Z)", re.S)

FM_LINE_RE = re.compile(r"(?P<key>\.?[A-Za-z_][A-Za-z0-9_-]*)[ \t]*:[ \t]*(?P<value>.*)")

METER_RE = re.compile(r"(?P<name>[A-Za-z0-9_./-]+)(?:\*(?P<slots>[1-9][0-9]*))?")


def _fm_scalar(text: str) -> Any:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    return text


def parse_frontmatter(body: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Return (fields, problems). fields is None when the body has no frontmatter block.

    The accepted YAML subset is flat: `key: scalar` or `key: [a, b]`. Anything
    else is a problem, so the parser never guesses.
    """
    m = FM_BLOCK_RE.match(body or "")
    if not m:
        return None, []
    fields: dict[str, Any] = {}
    problems: list[str] = []
    for n, raw in enumerate(m.group("yaml").splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        lm = FM_LINE_RE.fullmatch(line)
        if not lm:
            problems.append(f"line {n}: not 'key: value': {line.strip()[:60]}")
            continue
        key, value = lm.group("key"), lm.group("value").strip()
        if key in fields:
            problems.append(f"line {n}: duplicate key {key}")
            continue
        if value.startswith("["):
            if not value.endswith("]"):
                problems.append(f"line {n}: unterminated list for {key}")
                continue
            inner = value[1:-1].strip()
            fields[key] = [str(_fm_scalar(item)) for item in inner.split(",")] if inner else []
        else:
            fields[key] = _fm_scalar(value)
    return fields, problems


def validate_frontmatter(
    fields: dict[str, Any], self_ref: IssueRef
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Return (record, violations, warnings). References resolve relative to self_ref's repository."""
    v: list[str] = []
    w: list[str] = []
    slug = self_ref[0]
    for key in sorted(k for k in fields if k.startswith(FM_PREFIX) and k not in FM_KEYS):
        v.append(f"unknown key {key}")
    dag = fields.get(".dag")
    if dag in FM_RETIRED_SCHEMAS:
        v.append(f".dag {dag} is retired: {FM_RETIRED_SCHEMAS[dag]}")
    elif dag != FM_SCHEMA:
        v.append(f".dag must be {FM_SCHEMA}")
    own = parse_issue_ref(str(fields.get(".id", "")))
    if own is None:
        v.append(f".id {fields.get('.id')!r} must be owner/repo#N")
    elif own != self_ref:
        v.append(
            f".id {fields.get('.id')} does not name this issue ({node_id(*self_ref)}); was it transferred or copied?"
        )
    kind = fields.get(".kind")
    if kind not in FM_KINDS:
        v.append(".kind must be task or container")

    def refs(key: str) -> list[IssueRef]:
        raw = fields.get(key, [])
        if not isinstance(raw, list):
            v.append(f"{key} must be a list")
            return []
        out: list[IssueRef] = []
        for item in raw:
            r = parse_issue_ref(item)
            if r is None:
                v.append(
                    f"{key}: invalid reference {item!r} (use owner/repo#N; bare numbers are not allowed)"
                )
            elif r == self_ref:
                v.append(f"{key}: self reference")
            else:
                out.append(r)
        return out

    record: dict[str, Any] = {
        "kind": kind,
        "type": fields.get(".type"),
        "blocked_by": [],
        "children": [],
        "holds": [],
        "meters": [],
        "status": fields.get(".status"),
        "size_hours": fields.get(".size_hours"),
    }
    if kind == "task":
        if fields.get(".type") not in FM_TYPES:
            v.append(".type must be one of " + ", ".join(sorted(FM_TYPES)))
        if ".blocked_by" not in fields:
            v.append("a task needs .blocked_by (use [] for none)")
        if ".children" in fields:
            v.append("a task must not have .children")
        record["blocked_by"] = refs(".blocked_by")
    elif kind == "container":
        if ".children" not in fields:
            v.append("a container needs .children")
        if fields.get(".blocked_by"):
            v.append("a container must not have .blocked_by")
        record["children"] = refs(".children")
    holds = fields.get(".holds", [])
    if not isinstance(holds, list) or not all(isinstance(h, str) and h for h in holds):
        v.append(".holds must be a list of git-locks keys")
    else:
        record["holds"] = sorted(set(holds))
    meters = fields.get(".meters", [])
    if not isinstance(meters, list):
        v.append(".meters must be a list")
    else:
        for item in meters:
            mm = METER_RE.fullmatch(item)
            if not mm:
                v.append(f".meters: invalid entry {item!r} (use name or name*N)")
            else:
                record["meters"].append(
                    {"name": mm.group("name"), "slots": int(mm.group("slots") or 1)}
                )
    if record["status"] is not None and record["status"] not in FM_STATUSES:
        v.append(".status must be active, parked, or blocked")
    size = record["size_hours"]
    if size is not None:
        if not isinstance(size, int) or size <= 0:
            v.append(".size_hours must be a positive integer")
        elif size > FM_SIZE_WARN_HOURS:
            w.append(
                f".size_hours {size} is above {FM_SIZE_WARN_HOURS}; the card is probably not atomic"
            )
    return record, v, w


def rewrite_blocked_by(body: str, refs: list[IssueRef], base_slug: str) -> str | None:
    """Replace only the .blocked_by line of the frontmatter block. None when it cannot."""
    m = FM_BLOCK_RE.match(body or "")
    if not m:
        return None
    block = m.group("yaml")
    new_line = ".blocked_by: [" + ", ".join(format_ref_relative(r, base_slug) for r in refs) + "]"
    lines = block.splitlines()
    hits = [i for i, line in enumerate(lines) if re.match(r"\.blocked_by[ \t]*:", line)]
    if len(hits) != 1:
        return None
    lines[hits[0]] = new_line
    start, end = m.span("yaml")
    return body[:start] + "\n".join(lines) + body[end:]
