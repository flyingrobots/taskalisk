#!/usr/bin/env python3
"""A fake `gh` for offline tests. State lives in $FAKE_GH_STATE (JSON); every call is appended to $FAKE_GH_LOG.

State shape:
  {"home": "owner/repo",
   "default_author": "owner",             # author of issues that do not name one (association OWNER)
   "issues": {"owner/repo#N": {"id": int, "title": str, "state": "open"|"closed", "labels": [str], "body": str,
                               "state_reason": str|null,
                               "author": str|null, "author_type": "User"|"Bot", "association": str,
                               "editors": [str|null|{"login": str, "type": "Bot"}, ...],
                               "is_pr": bool,                  # listed by the REST issues endpoint as a pull request
                               "graphql_body": str}},          # body returned by GraphQL when it differs from REST
   "blocked_by": {"owner/repo#N": ["owner/repo#M", ...]},
   "prs": [{"number": int, "isDraft": bool, "url": str, "author": {"login": str}, "isCrossRepository": bool,
            "closingIssuesReferences": [{"number": int, "repository": {"name": str, "owner": {"login": str}}}]}],
   "collaborators": {"owner/repo": ["login", ...] | {"login": "write"|"triage"|...}},
   "collaborators_forbidden": bool,                   # 403 instead of 404
   "codeowners": {"owner/repo": {".github/CODEOWNERS": "text"}},
   "contents_fail": bool,                             # 500 from the contents endpoint
   "fail_graphql": bool,
   "fail_graphql_for": ["owner/repo#N", ...],         # GraphQL fails for these issues only
   "graphql_no_cursor": bool,                         # hasNextPage true without endCursor
   "edits_page_size": int}
"""

import json
import os
import re
import sys


def load():
    with open(os.environ["FAKE_GH_STATE"]) as f:
        return json.load(f)


def save(state):
    with open(os.environ["FAKE_GH_STATE"], "w") as f:
        json.dump(state, f)


def author_of(state, it):
    return it.get("author", state.get("default_author", "owner"))


def issue_obj(state, key):
    slug, num = key.split("#")
    it = state["issues"][key]
    author = author_of(state, it)
    obj = {
        "number": int(num),
        "id": it["id"],
        "title": it["title"],
        "state": it["state"],
        "state_reason": it.get("state_reason"),
        "labels": [{"name": n} for n in it.get("labels", [])],
        "body": it.get("body", ""),
        "milestone": None,
        "html_url": f"https://github.com/{slug}/issues/{num}",
        "repository_url": f"https://api.github.com/repos/{slug}",
        "user": {"login": author, "type": it.get("author_type", "User")} if author else None,
        "author_association": it.get("association", "OWNER"),
    }
    if it.get("is_pr"):
        obj["pull_request"] = {"url": f"https://api.github.com/repos/{slug}/pulls/{num}"}
    return obj


def strip(state, obj):
    if state.get("strip_repository_url"):
        obj.pop("repository_url", None)
    return obj


def fail(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)


def graphql(state, args):
    """The edit-history query: body and paginated body editors."""
    if "graphql_raw" in state:
        # Preserve deliberately malformed provider bytes at the transport boundary.
        sys.stdout.write(state["graphql_raw"])
        return
    if state.get("fail_graphql"):
        fail("gh: GraphQL unavailable (fake)")
    variables = {}
    i = 0
    while i < len(args):
        if args[i] in ("-f", "-F") and i + 1 < len(args):
            k, _, v = args[i + 1].partition("=")
            variables[k] = v
            i += 2
        else:
            i += 1
    key = f"{variables['owner']}/{variables['name']}#{variables['number']}"
    folded = {k.lower(): k for k in state["issues"]}
    key = folded.get(key.lower(), key)
    if key in state.get("fail_graphql_for", []):
        fail(f"gh: GraphQL unavailable for {key} (fake)")
    it = state["issues"].get(key)
    if it is None:
        print(
            json.dumps(
                {
                    "data": {"repository": {"issue": None}},
                    "errors": [{"message": "Could not resolve to an Issue"}],
                }
            )
        )
        sys.exit(1)
    author = author_of(state, it)
    # The creation edit is by the author actor, with the author's own type.
    editors = it.get("editors", [{"login": author, "type": it.get("author_type", "User")}])
    page = int(state.get("edits_page_size", 1000))
    start = int(variables.get("after") or 0)
    chunk = editors[start : start + page]
    has_next = start + page < len(editors)

    def node(e):
        if isinstance(e, dict):
            return {"editor": {"login": e.get("login"), "__typename": e.get("type", "User")}}
        return {"editor": {"login": e, "__typename": "User"} if e else None}

    edits = (
        None
        if state.get("graphql_null_edits")
        else {
            "pageInfo": {
                "hasNextPage": has_next,
                "endCursor": None if state.get("graphql_no_cursor") else str(start + page),
            },
            "nodes": [node(e) for e in chunk],
        }
    )
    out = {
        "data": {
            "repository": {
                "issue": {
                    "body": it.get("graphql_body", it.get("body", "")),
                    "userContentEdits": edits,
                }
            }
        }
    }
    print(json.dumps(out))


def main(argv):
    with open(os.environ["FAKE_GH_LOG"], "a") as f:
        f.write(json.dumps(argv) + "\n")
    state = load()
    if argv[:2] == ["repo", "view"]:
        print(state["home"])
        return
    if argv[:2] == ["issue", "list"]:
        out = [
            dict(issue_obj(state, k), url=issue_obj(state, k)["html_url"])
            for k, v in state["issues"].items()
            if k.lower().startswith(state["home"].lower() + "#") and v["state"] == "open"
        ]
        print(json.dumps(out))
        return
    if argv[:2] == ["pr", "list"]:
        # Like the real gh, return only the requested --json fields.
        prs = state.get("prs", [])
        if "--json" in argv:
            fields = argv[argv.index("--json") + 1].split(",")
            prs = [{k: v for k, v in pr.items() if k in fields} for pr in prs]
        print(json.dumps(prs))
        return
    if argv[0] != "api":
        fail(f"fake gh: unsupported command {argv}")
    if argv[1:2] == ["graphql"]:
        graphql(state, argv[2:])
        return
    args = []
    skip = False
    for a in argv[1:]:
        if skip:
            skip = False
            continue
        if a in ("--paginate", "--silent"):
            continue
        if a == "-H":
            skip = True
            continue
        args.append(a)
    method = "GET"
    if args[:1] == ["-X"]:
        method, args = args[1], args[2:]
    path = args[0]
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/issues\?state=open&per_page=\d+", path)
    if m:
        # The REST list: open issues of that repository, pull requests included, like GitHub.
        if "issues_list_raw" in state:
            # Fault injection at the CLI byte boundary, including empty/malformed output.
            sys.stdout.write(state["issues_list_raw"])
            return
        if state.get("issues_list_returns_object"):
            print("{}")
            return
        out = [
            issue_obj(state, k)
            for k, v in state["issues"].items()
            if k.lower().startswith(m.group(1).lower() + "#") and v["state"] == "open"
        ]
        print(json.dumps(out))
        return
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/collaborators/([^/]+)/permission", path)
    if m:
        # collaborators: {slug: [login, ...]} means write; {slug: {login: "triage"}} sets the level.
        table = next(
            (
                v
                for k, v in state.get("collaborators", {}).items()
                if k.lower() == m.group(1).lower()
            ),
            [],
        )
        perms = table if isinstance(table, dict) else {login: "write" for login in table}
        if m.group(2) in perms:
            print(perms[m.group(2)])
            return
        if state.get("collaborators_forbidden"):
            fail("gh: Must have push access to view repository collaborators (HTTP 403)")
        fail("gh: Not Found (HTTP 404)")
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/contents/(.+)", path)
    if m:
        if state.get("contents_fail"):
            fail("gh: Internal Server Error (HTTP 500)")
        text = next(
            (v for k, v in state.get("codeowners", {}).items() if k.lower() == m.group(1).lower()),
            {},
        ).get(m.group(2))
        if text is None:
            fail("gh: Not Found (HTTP 404)")
        print(text)
        return
    m = re.fullmatch(
        r"repos/([^/]+/[^/]+)/issues/(\d+)(/dependencies/blocked_by(?:/(\d+))?)?", path
    )
    if not m:
        fail(f"fake gh: unsupported path {path}")
    key = f"{m.group(1)}#{m.group(2)}"
    key = state.get("moved", {}).get(key, key)
    if key not in state["issues"]:
        # GitHub names are case-insensitive; find the issue under any spelling.
        folded = {k.lower(): k for k in state["issues"]}
        key = folded.get(key.lower(), key)
    if key not in state["issues"]:
        fail("gh: Not Found (HTTP 404)")
    if m.group(3) and state.get("blocked_by_fail"):
        fail("gh: Internal Server Error (HTTP 500)")
    if not m.group(3):
        if method == "GET" and state.get("issue_get_returns_list"):
            print("[]")
            return
        if method == "PATCH":
            payload = json.loads(sys.stdin.read())
            state["issues"][key]["body"] = payload["body"]
            save(state)
            print("{}")
            return
        if "--jq" in args and args[args.index("--jq") + 1] == ".id":
            print(state["issues"][key]["id"])
            return
        print(json.dumps(issue_obj(state, key)))
        return
    by_id = {v["id"]: k for k, v in state["issues"].items()}
    deps = state["blocked_by"].setdefault(key, [])
    if method == "GET":
        print(json.dumps([strip(state, issue_obj(state, b)) for b in deps]))
        return
    if method == "POST":
        field = next(a for a in args if a.startswith("issue_id="))
        parent = by_id[int(field.split("=", 1)[1])]
        if parent not in deps:
            deps.append(parent)
        save(state)
        print("{}")
        return
    if method == "DELETE":
        parent = by_id[int(m.group(4))]
        if parent in deps:
            deps.remove(parent)
        save(state)
        return
    fail(f"fake gh: unsupported method {method}")


main(sys.argv[1:])
