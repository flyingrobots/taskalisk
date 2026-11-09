"""Route the fake provider's REST requests with checked fixture containers."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import cast

from fake_fixture import emit, fail, issue_obj, issue_table, save, strip
from fake_values import fields, integer, items, text


@dataclass(frozen=True)
class ApiRequest:
    """The method, path and remaining flags parsed from owned test argv."""

    method: str
    path: str
    args: list[str]


def parse_request(argv: list[str]) -> ApiRequest:
    """Remove transport-only flags while retaining the endpoint's arguments."""
    args: list[str] = []
    skip = False
    for argument in argv[1:]:
        if skip:
            skip = False
            continue
        if argument in ("--paginate", "--silent"):
            continue
        if argument == "-H":
            skip = True
            continue
        args.append(argument)
    method = "GET"
    if args[:1] == ["-X"]:
        method, args = args[1], args[2:]
    return ApiRequest(method, args[0], args)


def listing(state: dict[str, object], request: ApiRequest) -> bool:
    """Serve REST issue seeds or an explicitly selected byte/shape fault."""
    match = re.fullmatch(r"repos/([^/]+/[^/]+)/issues\?state=open&per_page=\d+", request.path)
    if match is None:
        return False
    if "issues_list_raw" in state:
        sys.stdout.write(text(state["issues_list_raw"]))
    elif state.get("issues_list_returns_object"):
        emit({})
    else:
        prefix = match.group(1).lower() + "#"
        emit(
            [
                issue_obj(state, key, record)
                for key, record in issue_table(state).items()
                if key.lower().startswith(prefix) and record["state"] == "open"
            ]
        )
    return True


def permission(state: dict[str, object], request: ApiRequest) -> bool:
    """Project fixture collaborator permissions with the existing 403/404 faults."""
    match = re.fullmatch(r"repos/([^/]+/[^/]+)/collaborators/([^/]+)/permission", request.path)
    if match is None:
        return False
    empty: list[object] = []
    table = next(
        (
            value
            for key, value in fields(state.get("collaborators", {})).items()
            if key.lower() == match.group(1).lower()
        ),
        empty,
    )
    if isinstance(table, dict):
        # The checked container still needs key validation; values remain unknown.
        permissions = fields(cast("dict[object, object]", table))
    else:
        permissions = {text(login): "write" for login in items(table)}
    if match.group(2) in permissions:
        sys.stdout.write(str(permissions[match.group(2)]) + "\n")
        return True
    if state.get("collaborators_forbidden"):
        fail("gh: Must have push access to view repository collaborators (HTTP 403)")
    return fail("gh: Not Found (HTTP 404)")


def contents(state: dict[str, object], request: ApiRequest) -> bool:
    """Serve CODEOWNERS text from the requested repository and path."""
    match = re.fullmatch(r"repos/([^/]+/[^/]+)/contents/(.+)", request.path)
    if match is None:
        return False
    if state.get("contents_fail"):
        fail("gh: Internal Server Error (HTTP 500)")
    empty: dict[str, object] = {}
    table = next(
        (
            value
            for key, value in fields(state.get("codeowners", {})).items()
            if key.lower() == match.group(1).lower()
        ),
        empty,
    )
    content = fields(table).get(match.group(2))
    if content is None:
        fail("gh: Not Found (HTTP 404)")
    sys.stdout.write(text(content) + "\n")
    return True


def issue_body(
    state: dict[str, object], request: ApiRequest, key: str, records: dict[str, dict[str, object]]
) -> None:
    """Read or update an issue, preserving updates through copied fixture mappings."""
    if request.method == "GET" and state.get("issue_get_returns_list"):
        emit([])
        return
    if request.method == "PATCH":
        payload: object = json.loads(sys.stdin.read())
        records[key]["body"] = fields(payload)["body"]
        state["issues"] = records
        save(state)
        emit({})
        return
    if "--jq" in request.args and request.args[request.args.index("--jq") + 1] == ".id":
        sys.stdout.write(str(records[key]["id"]) + "\n")
        return
    emit(issue_obj(state, key, records[key]))


def dependencies(
    state: dict[str, object],
    request: ApiRequest,
    key: str,
    records: dict[str, dict[str, object]],
    parent_id: str | None,
) -> None:
    """Serve the existing relationship mirror fixture operations."""
    by_id = {integer(record["id"]): key for key, record in records.items()}
    table = fields(state["blocked_by"])
    parents = items(table.setdefault(key, []))
    state["blocked_by"] = table
    if request.method == "GET":
        emit(
            [
                strip(state, issue_obj(state, text(parent), records[text(parent)]))
                for parent in parents
            ]
        )
        return
    if request.method == "POST":
        field = next(arg for arg in request.args if arg.startswith("issue_id="))
        parent = by_id[int(field.split("=", 1)[1])]
        if parent not in parents:
            parents.append(parent)
        save(state)
        emit({})
        return
    if request.method == "DELETE":
        parent = by_id[int(text(parent_id))]
        if parent in parents:
            parents.remove(parent)
        save(state)
        return
    fail(f"fake gh: unsupported method {request.method}")


def issue_route(state: dict[str, object], request: ApiRequest) -> None:
    """Resolve case-folded and moved references before dispatching their operation."""
    match = re.fullmatch(
        r"repos/([^/]+/[^/]+)/issues/(\d+)(/dependencies/blocked_by(?:/(\d+))?)?", request.path
    )
    if match is None:
        fail(f"fake gh: unsupported path {request.path}")
    key = f"{match.group(1)}#{match.group(2)}"
    key = text(fields(state.get("moved", {})).get(key, key))
    records = issue_table(state)
    if key not in records:
        folded = {key.lower(): key for key in records}
        key = folded.get(key.lower(), key)
    if key not in records:
        fail("gh: Not Found (HTTP 404)")
    if match.group(3) and state.get("blocked_by_fail"):
        fail("gh: Internal Server Error (HTTP 500)")
    if match.group(3):
        dependencies(state, request, key, records, match.group(4))
    else:
        issue_body(state, request, key, records)


def dispatch(state: dict[str, object], argv: list[str]) -> None:
    """Use the explicit fixture routes, with issue operations as the final match."""
    request = parse_request(argv)
    for handler in (listing, permission, contents):
        if handler(state, request):
            return
    issue_route(state, request)
