"""Project paginated edit-history fixture data through the fake GraphQL route."""

from __future__ import annotations

import sys
from typing import cast

from fake_fixture import author_of, emit, fail, issue_table
from fake_values import fields, items, text


def edit_page_size(state: dict[str, object]) -> int:
    """Allow smaller test pages without exceeding the query's first:100 request."""
    value = state.get("edits_page_size", 100)
    if type(value) is not int or not 1 <= value <= 100:
        fail("fake gh: edits_page_size must be an integer from 1 to 100")
    return value


def variables_from(args: list[str]) -> dict[str, str]:
    """Read gh's supplied query variables without interpreting the query as instructions."""
    variables: dict[str, str] = {}
    index = 0
    while index < len(args):
        if args[index] in ("-f", "-F") and index + 1 < len(args):
            key, _, value = args[index + 1].partition("=")
            variables[key] = value
            index += 2
        else:
            index += 1
    return variables


def editor_node(value: object) -> dict[str, object]:
    """Keep explicit actor fixtures and nullable scalar shorthand unchanged."""
    if isinstance(value, dict):
        # isinstance establishes only dict; fields still checks every key.
        actor = fields(cast("dict[object, object]", value))
        return {"editor": {"login": actor.get("login"), "__typename": actor.get("type", "User")}}
    return {"editor": {"login": value, "__typename": "User"} if value else None}


def project_edits(
    state: dict[str, object], record: dict[str, object], after: str
) -> dict[str, object] | None:
    """Return one bounded page or the requested malformed-connection fixture."""
    author = author_of(state, record)
    editors = items(
        record.get("editors", [{"login": author, "type": record.get("author_type", "User")}])
    )
    page = edit_page_size(state)
    start = int(after or 0)
    if state.get("graphql_null_edits"):
        return None
    return {
        "pageInfo": {
            "hasNextPage": start + page < len(editors),
            "endCursor": None if state.get("graphql_no_cursor") else str(start + page),
        },
        "nodes": [editor_node(editor) for editor in editors[start : start + page]],
    }


def graphql(state: dict[str, object], args: list[str]) -> None:
    """Serve the edit-history query or its explicitly selected transport fault."""
    if "graphql_raw" in state:
        sys.stdout.write(text(state["graphql_raw"]))
        return
    if state.get("fail_graphql"):
        fail("gh: GraphQL unavailable (fake)")
    variables = variables_from(args)
    key = f"{variables['owner']}/{variables['name']}#{variables['number']}"
    records = issue_table(state)
    folded = {key.lower(): key for key in records}
    key = folded.get(key.lower(), key)
    if key in items(state.get("fail_graphql_for", [])):
        fail(f"gh: GraphQL unavailable for {key} (fake)")
    record = records.get(key)
    if record is None:
        emit(
            {
                "data": {"repository": {"issue": None}},
                "errors": [{"message": "Could not resolve to an Issue"}],
            }
        )
        sys.exit(1)
    emit(
        {
            "data": {
                "repository": {
                    "issue": {
                        "body": record.get("graphql_body", record.get("body", "")),
                        "userContentEdits": project_edits(
                            state, record, variables.get("after", "")
                        ),
                    }
                }
            }
        }
    )
