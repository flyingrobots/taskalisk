"""The Python compiler, run offline against the corpus's inputs.

A document case calls the compiler's parser and validator on a body and an address. A graph case
runs the compiler's discovery and compile (`compile_github`) with every `gh` and `git` call answered
from an observation bundle (corpus/bundle.md) instead of the network: an observed slot answers as
GitHub would, an unavailable one fails the call, and a slot the bundle lacks raises BundleIncomplete,
so a gap in a bundle is never read as an empty answer.

The results are projected into the corpus's expected form (corpus/README.md): the compiler's
messages become rule labels by `label_for`, which raises on a message it does not know.
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import pathlib
import re
import sys
from typing import Any, Iterator

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPILER = ROOT / "skills" / "taskalisk" / "scripts" / "taskalisk.py"
API = "https://api.github.com/repos/"
UNAVAILABLE = "observation unavailable: "
NOT_FOUND = "gh: Not Found (HTTP 404)"

_tk: Any = None


def compiler() -> Any:
    """The compiler module, loaded once from the checkout."""
    global _tk
    if _tk is None:
        spec = importlib.util.spec_from_file_location("taskalisk_compiler", COMPILER)
        module = importlib.util.module_from_spec(spec)
        sys.modules["taskalisk_compiler"] = module
        spec.loader.exec_module(module)
        _tk = module
    return _tk


class BundleIncomplete(Exception):
    """The run read an observation that the bundle does not record (OB5)."""


class UnlabelledMessage(Exception):
    """The compiler reported a message that no rule label is known for."""


class _Unavailable(Exception):
    pass


def _slot(slot: Any, what: str) -> Any:
    if slot is None:
        raise BundleIncomplete(f"the bundle does not record {what}")
    if "unavailable" in slot:
        raise _Unavailable(slot["unavailable"])
    return slot["value"]


class BundleForge:
    """Answers the compiler's `gh` and `git` commands from one bundle."""

    def __init__(self, bundle: dict[str, Any]):
        self.params = bundle["parameters"]
        self.obs = bundle["observations"]

    def __call__(self, cmd: list[str], cwd: str | None = None) -> tuple[bool, str, str]:
        try:
            return True, self.answer(cmd), ""
        except _Unavailable as exc:
            return False, "", UNAVAILABLE + str(exc)
        except _NotFound:
            return False, "", NOT_FOUND

    def issue(self, ref: str) -> dict[str, Any]:
        return _slot(self.obs["issues"].get(ref), f"the issue {ref}")

    def rest_issue(self, ref: str) -> dict[str, Any]:
        it = self.issue(ref)
        slug, num = it["address"].rsplit("#", 1)
        body = it["body"].get("value", {}).get("text", "") if isinstance(it["body"], dict) else ""
        obj = {"number": int(num), "id": 0, "title": "(title not recorded)", "state": it["state"], "state_reason": it["state_reason"],
               "body": body, "html_url": f"https://github.com/{slug}/issues/{num}", "repository_url": API + slug,
               "user": {"login": it["author"]["login"], "type": it["author"]["type"]} if it["author"] else None,
               "author_association": it["author_association"]}
        if it["pull_request"]:
            obj["pull_request"] = {"url": f"{API}{slug}/pulls/{num}"}
        return obj

    def answer(self, cmd: list[str]) -> str:
        if cmd[0] == "git":
            return ""  # branch names are hints outside the profile (section 13); none are recorded
        args = cmd[1:]
        if args[:2] == ["repo", "view"]:
            return self.params["home"]
        if args[:2] == ["pr", "list"]:
            prs = _slot(self.obs.get("home_open_pull_requests"), "the home pull requests")
            out = []
            for pr in prs:
                item: dict[str, Any] = {"number": pr["number"], "title": "", "headRefName": "", "url": f"https://github.com/{pr['repository']}/pull/{pr['number']}",
                                        "author": {"login": pr["author"]["login"], "is_bot": pr["author"]["type"] == "Bot"} if pr["author"] else None,
                                        "closingIssuesReferences": [{"number": int(c.rsplit("#", 1)[1]),
                                                                     "repository": {"name": c.split("/", 1)[1].split("#")[0], "owner": {"login": c.split("/", 1)[0]}}}
                                                                    for c in pr["closes"]]}
                if isinstance(pr["draft"], bool):
                    item["isDraft"] = pr["draft"]
                if pr["cross_repository"] is not None:
                    item["isCrossRepository"] = pr["cross_repository"]
                out.append(item)
            return json.dumps(out)
        if args[:2] == ["api", "graphql"]:
            v: dict[str, str] = {}
            for i, a in enumerate(args):
                if a in ("-f", "-F") and i + 1 < len(args):
                    k, _, val = args[i + 1].partition("=")
                    v[k] = val
            ref = f"{v['owner']}/{v['name']}#{v['number']}".lower()
            body = _slot(self.issue(ref)["body"], f"the body and edit history of {ref}")
            nodes = [{"editor": {"login": e["login"], "__typename": e["type"]} if e else None} for e in body["editors"]]
            return json.dumps({"data": {"repository": {"issue": {"body": body["text"], "userContentEdits": {
                "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}})
        if args[:1] != ["api"]:
            raise BundleIncomplete(f"the forge does not answer {cmd[:3]}")
        rest = [a for a in args[1:] if a not in ("--paginate", "--silent")]
        path = rest[0]
        m = re.fullmatch(r"repos/([^/]+/[^/]+)/issues\?state=open&per_page=\d+", path)
        if m:
            listing = _slot(self.obs.get("home_open_issues"), "the listing of open home issues")
            return json.dumps([self.rest_issue(ref) for ref in listing])
        m = re.fullmatch(r"repos/([^/]+/[^/]+)/collaborators/([^/]+)/permission", path)
        if m:
            table = self.obs["permissions"].get(m.group(1).lower())
            level = _slot((table or {}).get(m.group(2).lower()), f"the permission of {m.group(2)} on {m.group(1)}")
            if level is None:
                raise _NotFound()
            return level
        m = re.fullmatch(r"repos/([^/]+/[^/]+)/contents/(.+)", path)
        if m:
            found = _slot((self.obs.get("codeowners") or {}).get(m.group(1).lower()), f"the CODEOWNERS of {m.group(1)}")
            if found is None or found["path"] != m.group(2):
                raise _NotFound()
            return found["text"]
        m = re.fullmatch(r"repos/([^/]+/[^/]+)/issues/(\d+)", path)
        if m:
            return json.dumps(self.rest_issue(f"{m.group(1).lower()}#{int(m.group(2))}"))
        raise BundleIncomplete(f"the forge does not answer {path}")


class _NotFound(Exception):
    pass


@contextlib.contextmanager
def _answering(tk: Any, bundle: dict[str, Any]) -> Iterator[None]:
    saved = tk.run_cmd_checked
    tk.run_cmd_checked = BundleForge(bundle)
    try:
        yield
    finally:
        tk.run_cmd_checked = saved


def compile_bundle(bundle: dict[str, Any]) -> Any:
    """The compiler's Outcome for one bundle: discovery and compile, as `plan --from-github` runs them."""
    tk = compiler()
    params = bundle["parameters"]
    scope = params["read_scope"]
    trust = {"owners": scope["owners"], "repos": scope["repositories"], "logins": params["trust"]["logins"],
             "codeowners": params["trust"]["codeowners"]}
    out = tk.Outcome()
    exact_owners = {o.lower() for o in scope["owners"]}

    class RecordedScope(tk.TrustPolicy):
        """The compiler's policy, with exactly the bundle's read scope: the compiler always adds the home
        owner, but a bundle may record a narrower scope (the profile requires only the home repository)."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.owners = set(exact_owners)

    real_policy = tk.TrustPolicy
    tk.TrustPolicy = RecordedScope
    try:
        with _answering(tk, bundle):
            tk.compile_github(out, "<bundle>", list(params["roots"]), tk.DEFAULT_MIN_CONFIDENCE, dict(params["capacities"]) or None,
                              False, trust, [], None)
    finally:
        tk.TrustPolicy = real_policy
    return out


# --------------------------------------------------------------------------- #
# Rule labels for the compiler's messages
# --------------------------------------------------------------------------- #

# A format name (versions.md, U2): `issue-dag/` and a number written as in format rule L1.
FORMAT_NAME_RE = re.compile(r"issue-dag/[1-9][0-9]*")

# (pattern, label or a function of the document's fields)
_MESSAGES: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(r"line \d+: not 'key: value'"), "C6"),
    (re.compile(r"line \d+: duplicate key "), "C7"),
    (re.compile(r"line \d+: unterminated list for "), "C8"),
    (re.compile(r"unknown key \."), "V2"),
    (re.compile(r"\.dag \S+ is retired"), "P3"),
    # Format rule V12: P3 when .dag is another format name; V1 for any other value, or none.
    (re.compile(r"\.dag must be issue-dag/2"), lambda f: "P3" if isinstance(f.get(".dag"), str) and FORMAT_NAME_RE.fullmatch(f[".dag"]) else "V1"),
    # V12: L1 when .id is a string that is not a reference; V3 when it is absent or not a string.
    (re.compile(r"\.id .* must be owner/repo#N"), lambda f: "L1" if isinstance(f.get(".id"), str) else "V3"),
    (re.compile(r"\.id .* does not name this issue"), "X1"),
    (re.compile(r"\.kind must be task or container"), "V4"),
    (re.compile(r"\.type must be one of "), "V5"),
    (re.compile(r"a task needs \.blocked_by"), "V5"),
    (re.compile(r"a task must not have \.children"), "V5"),
    (re.compile(r"a container needs \.children"), "V6"),
    (re.compile(r"a container must not have \.blocked_by"), "V6"),
    (re.compile(r"\.blocked_by must be a list"), lambda f: "V6" if f.get(".kind") == "container" else "V5"),
    (re.compile(r"\.children must be a list"), "V6"),
    (re.compile(r"\.(blocked_by|children): invalid reference "), "L1"),
    (re.compile(r"\.(blocked_by|children): self reference"), "V7"),
    (re.compile(r"\.holds must be a list of git-locks keys"), lambda f: "L2" if isinstance(f.get(".holds"), list) else "V8"),
    (re.compile(r"\.meters must be a list"), "V8"),
    (re.compile(r"\.meters: invalid entry "), "L3"),
    (re.compile(r"\.status must be active, parked, or blocked"), "V8"),
    (re.compile(r"\.size_hours must be a positive integer"), lambda f: "L4" if isinstance(f.get(".size_hours"), int) else "V8"),
    (re.compile(r"\.size_hours \d+ is above \d+"), "V10"),
]
_DISCOVERY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"reference (?P<ref>\S+) is outside the trusted repositories"), "D3"),
    (re.compile(r"references a pull request, not an issue"), "D4"),
    (re.compile(r"reference (?P<ref>\S+) moved to \S+ \(transferred\)"), "D5"),
    (re.compile(r"\.blocked_by names container (?P<ref>\S+)"), "X2"),
]


def label_for(message: str, fields: dict[str, Any]) -> tuple[str, str | None]:
    """(rule label, the reference the finding concerns or None) for one compiler message."""
    for pattern, label in _DISCOVERY:
        m = pattern.match(message)
        if m:
            return label, m.groupdict().get("ref")
    for pattern, label in _MESSAGES:
        if pattern.match(message):
            return (label(fields) if callable(label) else label), None
    raise UnlabelledMessage(message)


# --------------------------------------------------------------------------- #
# Projections
# --------------------------------------------------------------------------- #


def _ref_text(ref: tuple[str, int]) -> str:
    return f"{ref[0]}#{ref[1]}"


def run_document(body: str, address: str) -> dict[str, Any]:
    """The compiler's judgement of one body held by the issue at `address`."""
    tk = compiler()
    fields, problems = tk.parse_frontmatter(body)
    if fields is None:
        return {"result": "no-document"}
    self_ref = tk.parse_issue_ref(address)
    try:
        record, violations, warnings = tk.validate_frontmatter(fields, self_ref)
    except Exception as exc:  # difference 7: the validator raises on some values
        return {"result": "error", "error": type(exc).__name__}
    labels = sorted({label_for(m, fields)[0] for m in problems + violations})
    warned = sorted({label_for(m, fields)[0] for m in warnings})
    if labels:
        return {"result": "invalid", "violations": labels, "warnings": warned}
    own = tk.parse_issue_ref(str(fields[".id"]))
    task = record["kind"] == "task"
    return {"result": "valid", "warnings": warned, "record": {
        "version": fields[".dag"], "id": _ref_text(own), "kind": record["kind"], "type": record["type"],
        "blocked_by": [_ref_text(r) for r in record["blocked_by"]] if task else None,
        "children": None if task else [_ref_text(r) for r in record["children"]],
        "size_hours": record["size_hours"], "holds": list(record["holds"]),
        "meters": [[m["name"], m["slots"]] for m in record["meters"]], "status": record["status"]}}


def _finding(subject: str, rule: str, concerns: str | None = None) -> dict[str, str]:
    f = {"subject": subject, "rule": rule}
    if concerns:
        f["concerns"] = concerns
    return f


def _sorted_unique(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {json.dumps(i, sort_keys=True): i for i in items}
    return [seen[k] for k in sorted(seen)]


def project_outcome(out: Any) -> dict[str, Any]:
    """The corpus's expected form of one compiler Outcome."""
    tk = compiler()
    codes = [f.code for f in out.failures]
    if any(c.startswith("root.") for c in codes):
        return {"outcome": "rejected"}
    if out.result is None or any(c.startswith(("gh.", "git.")) for c in codes):
        return {"outcome": "incomplete"}
    result, source = out.result, out.source
    by_id = {_ref_text(ref): ref for ref in source["fetched"]}

    def fields_of(nid: str) -> dict[str, Any]:
        meta = source["fetched"].get(by_id.get(nid))
        parsed = tk.parse_frontmatter(meta["body"])[0] if meta else None
        return parsed or {}

    findings = []
    fm = result.get("frontmatter") or {}
    for nid, messages in fm.get("violations", {}).items():
        for m in messages:
            findings.append(_finding(nid, *label_for(m, fields_of(nid))))
    for nid, messages in fm.get("warnings", {}).items():
        for m in messages:
            findings.append(_finding(nid, label_for(m, fields_of(nid))[0]))
    for u in result.get("unknown_dependencies", []):
        findings.append(_finding(u["node"], "X3", u["unknown_prerequisite"]))
    for nid in result.get("cyclic_nodes", []):
        findings.append(_finding(nid, "G4"))
    projected: dict[str, Any] = {"outcome": "planned" if result.get("ok") else "invalid", "findings": _sorted_unique(findings)}
    if "metrics" not in result:
        return projected

    nodes = []
    for ref, rec in source["records"].items():
        if rec["kind"] == "container":
            continue
        nid = _ref_text(ref)
        node = {"id": nid, "complete": source["fetched"][ref]["state"] == "closed", "opaque": rec["kind"] == "opaque",
                "untrusted": bool(rec.get("untrusted"))}
        if nid in source["nodes"]:
            node["status"] = source["nodes"][nid]["status"]
        nodes.append(node)
    waves = result["waves"]
    open_nodes = [n for items in waves.values() for n in items]
    edges = [{"from": e["from"], "to": e["to"], "status": "open"} for e in result["edges"]]
    edges += [{"from": e["from"], "to": e["to"], "status": "open"} for e in result["transitive_redundant_edges_removed"]]
    edges += [{"from": p, "to": n["id"], "status": "satisfied"} for n in open_nodes for p in n["completed_parents"]]
    skipped = []
    for s in result["batch_skipped"]:
        if s["reason"] == "holds conflict":
            skipped.append({"id": s["id"], "reason": "holds conflict"})
        else:
            names = s["reason"].split(": ", 1)[1].split(", ")
            skipped.append({"id": s["id"], "reason": "semaphore full", "semaphores": names})
    projected.update({
        "nodes": sorted(nodes, key=lambda n: n["id"]),
        "containers": sorted(({"id": c["id"], "children": c["children"]} for c in source["containers"]), key=lambda c: c["id"]),
        "unmodeled": sorted(u["id"] for u in source["unmodeled_open_issues"]),
        "untrusted": sorted(u["id"] for u in source["untrusted_issues"]),
        "untrusted_pull_requests": sorted(p["number"] for p in source["untrusted_linked_prs"]),
        "edges": sorted(edges, key=lambda e: (e["from"], e["to"], e["status"])),
        "redundant": sorted(({"from": e["from"], "to": e["to"]} for e in result["transitive_redundant_edges_removed"]), key=lambda e: (e["from"], e["to"])),
        "not_planned": sorted(({"from": n["parent"], "to": n["child"]} for n in source["not_planned_parents"]), key=lambda e: (e["from"], e["to"])),
        "ready": [n["id"] for n in result["open_frontier_ranked"]],
        "scores": {n["id"]: n["priority_score"] for n in sorted(open_nodes, key=lambda n: n["id"])},
        "batch": [b["id"] for b in result["conflict_free_frontier_batch"]],
        "skipped": skipped,
        "unknown_capacity": list(result["semaphores_with_unknown_capacity_treated_as_1"]),
        "waves": [[n["id"] for n in waves[k]] for k in sorted(waves, key=lambda k: int(k.rsplit(" ", 1)[1]))],
        "critical_path": list(result["metrics"]["critical_path"]),
    })
    return projected


def run_graph(bundle: dict[str, Any]) -> dict[str, Any]:
    """The compiler's plan for one bundle, in the corpus's expected form."""
    try:
        out = compile_bundle(bundle)
    except BundleIncomplete:
        raise
    except Exception as exc:
        return {"outcome": "error", "error": type(exc).__name__}
    return project_outcome(out)
