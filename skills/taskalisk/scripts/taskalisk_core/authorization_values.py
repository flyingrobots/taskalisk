"""Describe operator trust settings and the policy's public explanation."""

from __future__ import annotations

from typing import TypedDict


class TrustOptions(TypedDict, total=False):
    """Optional settings supplied by the operator's parsed CLI arguments."""

    owners: list[str]
    repos: list[str]
    logins: list[str]
    codeowners: bool


class TrustDescription(TypedDict):
    """Canonical trust scope and the CODEOWNERS evidence actually loaded."""

    owners: list[str]
    repos: list[str]
    logins: list[str]
    codeowners: dict[str, list[str]] | None
    codeowners_teams_not_expanded: dict[str, list[str]]
