"""Describe local Git observations and checked GitHub inventory output."""

from __future__ import annotations

from typing import TypedDict

from .github_inventory_values import InventoryIssue


class Worktree(TypedDict, total=False):
    """Fields observed in Git porcelain, including inaccessible or detached checkouts."""

    path: str
    path_exists: bool
    dirty: bool | None
    ahead_of_main: int
    behind_main: int
    head: str
    branch: str
    prunable: bool
    locked: bool


class Branch(TypedDict):
    """One unmerged branch and its available Git observations."""

    branch: str
    head: str
    ahead_of_main: int | None
    tip_subject: str


class BranchInventory(TypedDict):
    """Unmerged branches grouped by their local or remote namespace."""

    local: list[Branch]
    remote: list[Branch]


class GithubInventory(TypedDict):
    """Checked issue summaries alongside preserved, inventory-only PR wire metadata."""

    open_prs: list[dict[str, object]]
    open_issues: list[InventoryIssue]
