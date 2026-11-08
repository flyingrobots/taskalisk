#!/usr/bin/env python3
"""A fake `gh` for offline tests. State lives in $FAKE_GH_STATE (JSON); every call is appended to $FAKE_GH_LOG.

State shape:
  {"home": "owner/repo",
   "issues": {"owner/repo#N": {"id": int, "title": str, "state": "open"|"closed", "labels": [str], "body": str, "state_reason": str|null}},
   "blocked_by": {"owner/repo#N": ["owner/repo#M", ...]},
   "prs": [...]}
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
    args = [a for a in argv[1:] if a != "--paginate"]
    method = "GET"
    if args[:1] == ["-X"]:
        method, args = args[1], args[2:]
    path = args[0]
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
