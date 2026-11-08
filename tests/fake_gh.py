#!/usr/bin/env python3
"""A fake `gh` for offline tests. State lives in $FAKE_GH_STATE (JSON); every call is appended to $FAKE_GH_LOG.

State shape:
  {"home": "owner/repo",
   "default_author": "owner",             # author of issues that do not name one (association OWNER)
   "issues": {"owner/repo#N": {"id": int, "title": str, "state": "open"|"closed", "labels": [str], "body": str,
                               "state_reason": str|null,
                               "author": str|null, "association": str, "editors": [str|null, ...]}},
   "blocked_by": {"owner/repo#N": ["owner/repo#M", ...]},
   "prs": [{"number": int, "isDraft": bool, "url": str, "author": {"login": str}, "isCrossRepository": bool,
            "closingIssuesReferences": [{"number": int, "repository": {"name": str, "owner": {"login": str}}}]}],
   "collaborators": {"owner/repo": ["login", ...]},   # 204 from the collaborator check
   "collaborators_forbidden": bool,                   # 403 instead of 404
   "codeowners": {"owner/repo": {".github/CODEOWNERS": "text"}},
   "fail_graphql": bool,
   "edits_page_size": int}
"""
import json, os, re, sys

def load():
    with open(os.environ["FAKE_GH_STATE"]) as f:
        return json.load(f)

def save(state):
    with open(os.environ["FAKE_GH_STATE"], "w") as f:
        json.dump(state, f)

def issue_obj(state, key):
    slug, num = key.split("#")
    it = state["issues"][key]
    return {"number": int(num), "id": it["id"], "title": it["title"], "state": it["state"],
            "state_reason": it.get("state_reason"), "labels": [{"name": n} for n in it.get("labels", [])],
            "body": it.get("body", ""), "milestone": None,
            "html_url": f"https://github.com/{slug}/issues/{num}",
            "repository_url": f"https://api.github.com/repos/{slug}"}

def strip(state, obj):
    if state.get("strip_repository_url"):
        obj.pop("repository_url", None)
    return obj

def fail(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

def graphql(state, args):
    """The trust query: author, association and paginated body editors."""
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
    it = state["issues"].get(key)
    if it is None:
        print(json.dumps({"data": {"repository": {"issue": None}}, "errors": [{"message": "Could not resolve to an Issue"}]}))
        sys.exit(1)
    author = it.get("author", state.get("default_author", "owner"))
    editors = it.get("editors", [author])
    page = int(state.get("edits_page_size", 1000))
    start = int(variables.get("after") or 0)
    chunk = editors[start:start + page]
    out = {"data": {"repository": {"issue": {
        "author": {"login": author} if author else None,
        "authorAssociation": it.get("association", "OWNER"),
        "userContentEdits": {"pageInfo": {"hasNextPage": start + page < len(editors), "endCursor": str(start + page)},
                             "nodes": [{"editor": {"login": e} if e else None} for e in chunk]}}}}}
    print(json.dumps(out))

def main(argv):
    with open(os.environ["FAKE_GH_LOG"], "a") as f:
        f.write(json.dumps(argv) + "\n")
    state = load()
    if argv[:2] == ["repo", "view"]:
        print(state["home"]); return
    if argv[:2] == ["issue", "list"]:
        out = [dict(issue_obj(state, k), url=issue_obj(state, k)["html_url"]) for k, v in state["issues"].items()
               if k.startswith(state["home"] + "#") and v["state"] == "open"]
        print(json.dumps(out)); return
    if argv[:2] == ["pr", "list"]:
        print(json.dumps(state.get("prs", []))); return
    if argv[0] != "api":
        fail(f"fake gh: unsupported command {argv}")
    if argv[1:2] == ["graphql"]:
        graphql(state, argv[2:]); return
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
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/collaborators/([^/]+)", path)
    if m:
        if m.group(2) in state.get("collaborators", {}).get(m.group(1), []):
            return
        if state.get("collaborators_forbidden"):
            fail("gh: Must have push access to view repository collaborators (HTTP 403)")
        fail("gh: Not Found (HTTP 404)")
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/contents/(.+)", path)
    if m:
        text = state.get("codeowners", {}).get(m.group(1), {}).get(m.group(2))
        if text is None:
            fail("gh: Not Found (HTTP 404)")
        print(text); return
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/issues/(\d+)(/dependencies/blocked_by(?:/(\d+))?)?", path)
    if not m:
        fail(f"fake gh: unsupported path {path}")
    key = f"{m.group(1)}#{m.group(2)}"
    key = state.get("moved", {}).get(key, key)
    if key not in state["issues"]:
        fail("gh: Not Found (HTTP 404)")
    if not m.group(3):
        if method == "PATCH":
            payload = json.loads(sys.stdin.read())
            state["issues"][key]["body"] = payload["body"]
            save(state); print("{}"); return
        if "--jq" in args and args[args.index("--jq") + 1] == ".id":
            print(state["issues"][key]["id"]); return
        print(json.dumps(issue_obj(state, key))); return
    by_id = {v["id"]: k for k, v in state["issues"].items()}
    deps = state["blocked_by"].setdefault(key, [])
    if method == "GET":
        print(json.dumps([strip(state, issue_obj(state, b)) for b in deps])); return
    if method == "POST":
        field = next(a for a in args if a.startswith("issue_id="))
        parent = by_id[int(field.split("=", 1)[1])]
        if parent not in deps:
            deps.append(parent)
        save(state); print("{}"); return
    if method == "DELETE":
        parent = by_id[int(m.group(4))]
        if parent in deps:
            deps.remove(parent)
        save(state); return
    fail(f"fake gh: unsupported method {method}")

main(sys.argv[1:])
