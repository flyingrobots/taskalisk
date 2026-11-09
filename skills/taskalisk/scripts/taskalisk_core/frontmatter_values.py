"""Describe parsed format values without claiming that their semantics are valid."""

from __future__ import annotations

from typing import TypedDict, Union

from .issue_refs import IssueRef

FieldValue = Union[str, int, list[str]]
ParsedFields = dict[str, FieldValue]


class Meter(TypedDict):
    """A parsed semaphore name and requested slot count."""

    name: str
    slots: int


class _RecordFields(TypedDict):
    """Required parsing output; violations determine whether it can be used."""

    kind: FieldValue | None
    type: FieldValue | None
    blocked_by: list[IssueRef]
    children: list[IssueRef]
    holds: list[str]
    meters: list[Meter]
    status: FieldValue | None
    size_hours: FieldValue | None


class FrontmatterRecord(_RecordFields, total=False):
    """Parsing output with an optional admission marker for opaque records."""

    untrusted: bool
