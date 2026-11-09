"""Parse, validate and rewrite the issue-dag frontmatter format."""

from __future__ import annotations

import re

from .frontmatter_values import FrontmatterRecord, ParsedFields
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


def _fm_scalar(text: str) -> str | int:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    return text


def parse_frontmatter(body: str) -> tuple[ParsedFields | None, list[str]]:
    """Return (fields, problems). fields is None when the body has no frontmatter block.

    The accepted YAML subset is flat: `key: scalar` or `key: [a, b]`. Anything
    else is a problem, so the parser never guesses.
    """
    m = FM_BLOCK_RE.match(body or "")
    if not m:
        return None, []
    fields: ParsedFields = {}
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


def _validate_identity(fields: ParsedFields, self_ref: IssueRef) -> list[str]:
    """Check schema, identity and kind before reading structural fields."""
    violations = [
        f"unknown key {key}"
        for key in sorted(key for key in fields if key.startswith(FM_PREFIX) and key not in FM_KEYS)
    ]
    dag = fields.get(".dag")
    if isinstance(dag, str) and dag in FM_RETIRED_SCHEMAS:
        violations.append(f".dag {dag} is retired: {FM_RETIRED_SCHEMAS[dag]}")
    elif dag != FM_SCHEMA:
        violations.append(f".dag must be {FM_SCHEMA}")
    own = parse_issue_ref(str(fields.get(".id", "")))
    if own is None:
        violations.append(f".id {fields.get('.id')!r} must be owner/repo#N")
    elif own != self_ref:
        violations.append(
            f".id {fields.get('.id')} does not name this issue ({node_id(*self_ref)}); was it transferred or copied?"
        )
    kind = fields.get(".kind")
    if not isinstance(kind, str) or kind not in FM_KINDS:
        violations.append(".kind must be task or container")
    return violations


def _references(
    fields: ParsedFields, key: str, self_ref: IssueRef, violations: list[str]
) -> list[IssueRef]:
    """Parse a reference list and retain its exact refusal diagnostics."""
    raw = fields.get(key, [])
    if not isinstance(raw, list):
        violations.append(f"{key} must be a list")
        return []
    references: list[IssueRef] = []
    for item in raw:
        reference = parse_issue_ref(item)
        if reference is None:
            violations.append(
                f"{key}: invalid reference {item!r} (use owner/repo#N; bare numbers are not allowed)"
            )
        elif reference == self_ref:
            violations.append(f"{key}: self reference")
        else:
            references.append(reference)
    return references


def _read_structure(
    fields: ParsedFields, self_ref: IssueRef, record: FrontmatterRecord, violations: list[str]
) -> None:
    """Keep task dependencies distinct from container membership."""
    if record["kind"] == "task":
        task_type = fields.get(".type")
        if not isinstance(task_type, str) or task_type not in FM_TYPES:
            violations.append(".type must be one of " + ", ".join(sorted(FM_TYPES)))
        if ".blocked_by" not in fields:
            violations.append("a task needs .blocked_by (use [] for none)")
        if ".children" in fields:
            violations.append("a task must not have .children")
        record["blocked_by"] = _references(fields, ".blocked_by", self_ref, violations)
    elif record["kind"] == "container":
        if ".children" not in fields:
            violations.append("a container needs .children")
        if fields.get(".blocked_by"):
            violations.append("a container must not have .blocked_by")
        record["children"] = _references(fields, ".children", self_ref, violations)


def _read_resources(fields: ParsedFields, record: FrontmatterRecord, violations: list[str]) -> None:
    """Normalize exclusive keys and decode semaphore requests."""
    holds = fields.get(".holds", [])
    # The parser constructs lists of strings; empty keys are still invalid.
    if not isinstance(holds, list) or not all(holds):
        violations.append(".holds must be a list of git-locks keys")
    else:
        record["holds"] = sorted(set(holds))
    meters = fields.get(".meters", [])
    if not isinstance(meters, list):
        violations.append(".meters must be a list")
        return
    for item in meters:
        match = METER_RE.fullmatch(item)
        if not match:
            violations.append(f".meters: invalid entry {item!r} (use name or name*N)")
        else:
            record["meters"].append(
                {"name": match.group("name"), "slots": int(match.group("slots") or 1)}
            )


def _check_status_and_size(
    record: FrontmatterRecord, violations: list[str], warnings: list[str]
) -> None:
    """Reject invalid scheduling fields and warn about oversized tasks."""
    status = record["status"]
    if status is not None and (not isinstance(status, str) or status not in FM_STATUSES):
        violations.append(".status must be active, parked, or blocked")
    size = record["size_hours"]
    if size is None:
        return
    if not isinstance(size, int) or size <= 0:
        violations.append(".size_hours must be a positive integer")
    elif size > FM_SIZE_WARN_HOURS:
        warnings.append(
            f".size_hours {size} is above {FM_SIZE_WARN_HOURS}; the card is probably not atomic"
        )


def validate_frontmatter(
    fields: ParsedFields, self_ref: IssueRef
) -> tuple[FrontmatterRecord, list[str], list[str]]:
    """Validate parser output; nonempty violations forbid dispatch.

    References must be qualified. Scalar fields remain visible in the record even
    when invalid; the accompanying violations are the admission decision.
    """
    record: FrontmatterRecord = {
        "kind": fields.get(".kind"),
        "type": fields.get(".type"),
        "blocked_by": [],
        "children": [],
        "holds": [],
        "meters": [],
        "status": fields.get(".status"),
        "size_hours": fields.get(".size_hours"),
    }
    violations = _validate_identity(fields, self_ref)
    warnings: list[str] = []
    _read_structure(fields, self_ref, record, violations)
    _read_resources(fields, record, violations)
    _check_status_and_size(record, violations, warnings)
    return record, violations, warnings


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
