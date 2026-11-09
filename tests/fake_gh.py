#!/usr/bin/env python3
"""Serve the offline gh contract from owned state and an append-only call log."""

from __future__ import annotations

import json
import os
import sys

from fake_api import dispatch
from fake_fixture import emit, fail, issue_obj, issue_table, load
from fake_history import graphql
from fake_values import fields, items, text


def list_issues(state: dict[str, object]) -> None:
    """Project open issues in the home repository for the inventory command."""
    prefix = text(state["home"]).lower() + "#"
    result: list[dict[str, object]] = []
    for key, record in issue_table(state).items():
        if key.lower().startswith(prefix) and record["state"] == "open":
            obj = issue_obj(state, key, record)
            result.append(dict(obj, url=obj["html_url"]))
    emit(result)


def list_prs(state: dict[str, object], argv: list[str]) -> None:
    """Return only the requested PR wire fields, including deliberately invalid values."""
    prs = [fields(value) for value in items(state.get("prs", []))]
    if "--json" in argv:
        requested = argv[argv.index("--json") + 1].split(",")
        prs = [{key: value for key, value in pr.items() if key in requested} for pr in prs]
    emit(prs)


def main(argv: list[str]) -> None:
    """Record the call and dispatch the fixture's repository, inventory or API route."""
    with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as stream:
        stream.write(json.dumps(argv) + "\n")
    state = load()
    if argv[:2] == ["repo", "view"]:
        sys.stdout.write(text(state["home"]) + "\n")
    elif argv[:2] == ["issue", "list"]:
        list_issues(state)
    elif argv[:2] == ["pr", "list"]:
        list_prs(state, argv)
    elif argv[:2] == ["api", "graphql"]:
        graphql(state, argv[2:])
    elif argv[:1] == ["api"]:
        dispatch(state, argv)
    else:
        fail(f"fake gh: unsupported command {argv}")


if __name__ == "__main__":
    main(sys.argv[1:])
