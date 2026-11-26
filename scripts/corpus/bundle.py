"""Observation bundles (issue-dag specification, corpus/bundle.md): the complete input of one
planning run, so that the plan can be computed again offline from the bundle alone.

`validate` checks a bundle against the rules OB1 to OB14. `from_fake_state` records, as a bundle,
the observations a run would make against a tests/fake_gh.py state.
"""
from __future__ import annotations

import re
from typing import Any

BUNDLE_VERSION = "issue-dag-observations/1"
FORMAT = "issue-dag/2"
PROFILE = "issue-dag-planning/2"
TRUST_POLICY = "taskalisk/threat-model"
CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
REF_RE = re.compile(r"(?P<slug>[a-z0-9_.-]+/[a-z0-9_.-]+)#(?P<num>[1-9][0-9]*)")
REPO_RE = re.compile(r"[a-z0-9_.-]+/[a-z0-9_.-]+")
OWNER_RE = re.compile(r"[a-z0-9_.-]+")
STATES = ("open", "closed")


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _slot(problems: list[str], where: str, slot: Any) -> tuple[bool, Any]:
    """OB4: a slot is {"value": v} or {"unavailable": "reason"}. Returns (observed, value)."""
    if not isinstance(slot, dict) or len(slot) != 1 or not ({"value", "unavailable"} & set(slot)):
        problems.append(f"{where}: an observation is exactly one of {{\"value\": ...}} or {{\"unavailable\": \"reason\"}} (OB4)")
        return False, None
    if "unavailable" in slot:
        if not isinstance(slot["unavailable"], str) or not slot["unavailable"].strip():
            problems.append(f"{where}: an unavailable observation names its reason (OB4)")
        return False, None
    return True, slot["value"]


def _ref(problems: list[str], where: str, text: Any) -> bool:
    if not isinstance(text, str) or not REF_RE.fullmatch(text) or int(text.rsplit("#", 1)[1]) > 2147483647:
        problems.append(f"{where}: {text!r} is not a reference in canonical form (OB13)")
        return False
    return True


def _actor(problems: list[str], where: str, actor: Any, nullable: bool = True) -> None:
    if actor is None and nullable:
        return
    if not isinstance(actor, dict) or set(actor) != {"login", "type"} or not isinstance(actor["login"], str) or not actor["login"] \
            or not isinstance(actor["type"], str):
        problems.append(f"{where}: an actor is {{\"login\": str, \"type\": str}} or null (OB9)")


def _keys(problems: list[str], where: str, obj: Any, required: set[str], optional: set[str] = frozenset()) -> bool:
    if not isinstance(obj, dict):
        problems.append(f"{where}: must be an object")
        return False
    missing, extra = required - set(obj), set(obj) - required - set(optional)
    if missing:
        problems.append(f"{where}: missing {', '.join(sorted(missing))}")
    if extra:
        problems.append(f"{where}: unknown member {', '.join(sorted(extra))}")
    return not missing and not extra


def _in_scope(params: dict[str, Any], slug: str) -> bool:
    scope = params.get("read_scope") or {}
    return slug in (scope.get("repositories") or []) or slug.split("/", 1)[0] in (scope.get("owners") or [])


def validate(bundle: Any) -> list[str]:
    """Every way `bundle` fails corpus/bundle.md; empty when it is a valid bundle."""
    p: list[str] = []
    if not _keys(p, "bundle", bundle, {"bundle", "format", "profile", "parameters", "observations"}):
        if not isinstance(bundle, dict):
            return p
    if bundle.get("bundle") != BUNDLE_VERSION:
        p.append(f"bundle: the version field must be {BUNDLE_VERSION!r} (OB1)")
    if bundle.get("format") != FORMAT or bundle.get("profile") != PROFILE:
        p.append(f"bundle: format and profile must name {FORMAT} and {PROFILE} (OB2)")
    params = bundle.get("parameters")
    if _keys(p, "parameters", params, {"home", "roots", "read_scope", "trust", "capacities"}):
        if not isinstance(params["home"], str) or not REPO_RE.fullmatch(params["home"]):
            p.append("parameters.home: a repository in canonical form (OB3)")
        if not isinstance(params["roots"], list) or not all(isinstance(r, str) for r in params["roots"]):
            p.append("parameters.roots: a list of strings (OB3)")
        scope = params["read_scope"]
        if _keys(p, "parameters.read_scope", scope, {"owners", "repositories"}):
            if not all(isinstance(o, str) and OWNER_RE.fullmatch(o) for o in scope["owners"]) or \
                    not all(isinstance(r, str) and REPO_RE.fullmatch(r) for r in scope["repositories"]):
                p.append("parameters.read_scope: owners and repositories in canonical form (OB3)")
            elif isinstance(params["home"], str) and not _in_scope(params, params["home"]):
                p.append("parameters.read_scope: the read scope must include the home repository (OB3)")
        trust = params["trust"]
        if _keys(p, "parameters.trust", trust, {"policy", "logins", "codeowners"}):
            if not isinstance(trust["policy"], str) or not trust["policy"] or not isinstance(trust["codeowners"], bool) \
                    or not all(isinstance(x, str) and x for x in trust["logins"]):
                p.append("parameters.trust: a policy name, a list of logins and a boolean (OB3)")
        caps = params["capacities"]
        if not isinstance(caps, dict) or not all(isinstance(k, str) and k and type(v) is int and v >= 1 for k, v in caps.items()):
            p.append("parameters.capacities: names to positive integers (OB3)")
    obs = bundle.get("observations")
    if not _keys(p, "observations", obs, {"home_open_pull_requests", "issues", "permissions"}, {"home_open_issues", "codeowners"}):
        if not isinstance(obs, dict):
            return p
    params = params if isinstance(params, dict) else {}
    roots = params.get("roots") or []
    if not roots and "home_open_issues" not in obs:
        p.append("observations.home_open_issues: a run without roots records the home listing (OB6)")
    if roots and "home_open_issues" in obs:
        p.append("observations.home_open_issues: a run with roots does not read the home listing (OB6)")
    issues = obs.get("issues", {})
    if not isinstance(issues, dict):
        p.append("observations.issues: must be an object")
        issues = {}
    if "home_open_issues" in obs:
        ok, listing = _slot(p, "observations.home_open_issues", obs["home_open_issues"])
        if ok:
            if not isinstance(listing, list):
                p.append("observations.home_open_issues: the value is a list of references (OB6)")
            else:
                for ref in listing:
                    if _ref(p, "observations.home_open_issues", ref) and not ref.startswith(params.get("home", "") + "#"):
                        p.append(f"observations.home_open_issues: {ref} is not in the home repository (OB6)")
                if len(set(listing)) != len(listing):
                    p.append("observations.home_open_issues: a reference is listed twice (OB6)")
    if "home_open_pull_requests" in obs:
        ok, prs = _slot(p, "observations.home_open_pull_requests", obs["home_open_pull_requests"])
        if ok:
            if not isinstance(prs, list):
                p.append("observations.home_open_pull_requests: the value is a list (OB7)")
                prs = []
            for i, pr in enumerate(prs):
                where = f"observations.home_open_pull_requests[{i}]"
                if not _keys(p, where, pr, {"number", "repository", "head_repository", "cross_repository", "author", "draft", "closes"}):
                    continue
                if type(pr["number"]) is not int or pr["number"] < 1:
                    p.append(f"{where}.number: a positive integer (OB7)")
                if pr["repository"] != params.get("home"):
                    p.append(f"{where}.repository: a pull request of the home repository (OB7)")
                if pr["head_repository"] is not None and not (isinstance(pr["head_repository"], str) and REPO_RE.fullmatch(pr["head_repository"])):
                    p.append(f"{where}.head_repository: a repository or null (OB7)")
                if pr["cross_repository"] not in (True, False, None):
                    p.append(f"{where}.cross_repository: a boolean or null (OB7)")
                _actor(p, f"{where}.author", pr["author"])
                if not isinstance(pr["draft"], bool):
                    _slot(p, f"{where}.draft", pr["draft"])
                    if isinstance(pr["draft"], dict) and "value" in pr["draft"]:
                        p.append(f"{where}.draft: an observed draft flag is a boolean; otherwise it is unavailable (OB7)")
                if not isinstance(pr["closes"], list) or not all(_ref(p, f"{where}.closes", r) for r in pr["closes"]):
                    p.append(f"{where}.closes: a list of references (OB7)")
    for ref, slot in issues.items():
        where = f"observations.issues[{ref}]"
        if not _ref(p, where, ref):
            continue
        if not _in_scope(params, ref.split("#", 1)[0]):
            p.append(f"{where}: a reference outside the read scope is never read (OB8)")
        ok, it = _slot(p, where, slot)
        if not ok or not _keys(p, where, it, {"address", "pull_request", "state", "state_reason", "author", "author_association", "body"}):
            continue
        _ref(p, f"{where}.address", it["address"])
        if not isinstance(it["pull_request"], bool):
            p.append(f"{where}.pull_request: a boolean (OB8)")
        if it["state"] not in STATES:
            p.append(f"{where}.state: open or closed (OB8)")
        if it["state_reason"] is not None and not isinstance(it["state_reason"], str):
            p.append(f"{where}.state_reason: a string or null (OB8)")
        _actor(p, f"{where}.author", it["author"])
        if it["author_association"] is not None and not isinstance(it["author_association"], str):
            p.append(f"{where}.author_association: a string or null (OB8)")
        ok, body = _slot(p, f"{where}.body", it["body"])
        if ok and _keys(p, f"{where}.body", body, {"text", "editors"}):
            if not isinstance(body["text"], str):
                p.append(f"{where}.body.text: a string (OB8)")
            if not isinstance(body["editors"], list):
                p.append(f"{where}.body.editors: a list (OB8)")
            else:
                for e in body["editors"]:
                    _actor(p, f"{where}.body.editors", e)
    perms = obs.get("permissions", {})
    if not isinstance(perms, dict):
        p.append("observations.permissions: an object (OB10)")
        perms = {}
    for repo, table in perms.items():
        if not REPO_RE.fullmatch(repo) or not isinstance(table, dict):
            p.append(f"observations.permissions[{repo}]: a repository in canonical form, to an object of logins (OB10)")
            continue
        for login, slot in table.items():
            if login != login.lower():
                p.append(f"observations.permissions[{repo}][{login}]: logins are recorded in lower case (OB10)")
            ok, value = _slot(p, f"observations.permissions[{repo}][{login}]", slot)
            if ok and value is not None and not isinstance(value, str):
                p.append(f"observations.permissions[{repo}][{login}]: a permission string or null (OB10)")
    if "codeowners" in obs:
        if not params.get("trust", {}).get("codeowners"):
            p.append("observations.codeowners: recorded only when the trust policy reads CODEOWNERS (OB11)")
        for repo, slot in (obs["codeowners"] or {}).items():
            ok, value = _slot(p, f"observations.codeowners[{repo}]", slot)
            if ok and value is not None and not (_keys(p, f"observations.codeowners[{repo}]", value, {"path", "text"})
                                                 and value["path"] in CODEOWNERS_PATHS and isinstance(value["text"], str)):
                p.append(f"observations.codeowners[{repo}]: {{path, text}} or null (OB11)")
    return p


# --------------------------------------------------------------------------- #
# From a tests/fake_gh.py state
# --------------------------------------------------------------------------- #


def _canonical_ref(text: str) -> str:
    slug, num = text.rsplit("#", 1)
    return f"{slug.lower()}#{int(num)}"


def _actor_of(login: Any, actor_type: str = "User") -> dict[str, str] | None:
    return {"login": login, "type": actor_type} if login else None


def from_fake_state(state: dict[str, Any], roots: list[str] | tuple[str, ...] = (), trust: dict[str, Any] | None = None,
                    capacities: dict[str, int] | None = None) -> dict[str, Any]:
    """The bundle of a run of the compiler against `state` with these parameters (`trust` as the
    compiler's trust_of: owners, repos, logins, codeowners). Every issue the state holds inside the
    read scope is recorded, whether or not a given planner reads it; nothing outside is."""
    trust = trust or {}
    home = state["home"].lower()
    owners = sorted({home.split("/", 1)[0], *(o.lower() for o in trust.get("owners", []))})
    repos = sorted({r.lower() for r in trust.get("repos", [])})
    params = {"home": home, "roots": list(roots), "read_scope": {"owners": owners, "repositories": repos},
              "trust": {"policy": TRUST_POLICY, "logins": list(trust.get("logins", [])), "codeowners": bool(trust.get("codeowners"))},
              "capacities": dict(capacities or {})}
    default_author = state.get("default_author", "owner")
    keys = {k.lower(): k for k in state["issues"]}

    def raw(key: str) -> dict[str, Any]:
        return state["issues"][keys[key.lower()]]

    def author(it: dict[str, Any]) -> Any:
        return it.get("author", default_author)

    def record(it: dict[str, Any], address: str) -> dict[str, Any]:
        login = author(it)
        editors = it.get("editors", [{"login": login, "type": it.get("author_type", "User")}])
        eds = [(_actor_of(e.get("login"), e.get("type", "User")) if isinstance(e, dict) else _actor_of(e)) for e in editors]
        body: dict[str, Any] = {"value": {"text": it.get("graphql_body", it.get("body", "")), "editors": eds}}
        if state.get("fail_graphql") or address in [_canonical_ref(x) for x in state.get("fail_graphql_for", [])]:
            body = {"unavailable": "the edit-history query failed"}
        elif state.get("graphql_null_edits") or state.get("graphql_no_cursor") or state.get("graphql_repeat_cursor"):
            body = {"unavailable": "the edit history could not be read in full"}
        return {"address": address, "pull_request": bool(it.get("is_pr")), "state": it["state"], "state_reason": it.get("state_reason"),
                "author": _actor_of(login, it.get("author_type", "User")), "author_association": it.get("association", "OWNER"),
                "body": body}

    issues: dict[str, Any] = {}
    moved = {_canonical_ref(k): _canonical_ref(v) for k, v in state.get("moved", {}).items()}
    candidates = {_canonical_ref(k) for k in state["issues"]} | set(moved)
    for ref in sorted(candidates):
        if not _in_scope(params, ref.split("#", 1)[0]):
            continue
        address = moved.get(ref, ref)
        if address.lower() not in keys:
            issues[ref] = {"unavailable": "not found"}
            continue
        if ref not in moved and ref != address:
            continue
        issues[ref] = {"value": record(raw(address), address)}

    prs = []
    for pr in state.get("prs", []):
        closes = []
        for c in pr.get("closingIssuesReferences", []) or []:
            repo = c.get("repository") or {}
            slug = f"{repo['owner']['login']}/{repo['name']}".lower() if repo.get("name") and (repo.get("owner") or {}).get("login") else home
            closes.append(f"{slug}#{int(c['number'])}")
        a = pr.get("author") or {}
        cross = pr.get("isCrossRepository") if isinstance(pr.get("isCrossRepository"), bool) else None
        prs.append({"number": pr["number"], "repository": home, "head_repository": None if cross is not False else home,
                    "cross_repository": cross, "author": _actor_of(a.get("login"), "Bot" if a.get("is_bot") else "User"),
                    "draft": pr["isDraft"] if isinstance(pr.get("isDraft"), bool) else {"unavailable": "the draft flag is not a boolean"},
                    "closes": closes})
    observations: dict[str, Any] = {"home_open_pull_requests": {"value": prs}, "issues": issues}
    if not roots:
        if state.get("issues_list_fail_message") or state.get("issues_list_returns_object") or state.get("issues_list_drop_number"):
            observations["home_open_issues"] = {"unavailable": "the listing of open issues failed"}
        else:
            listing = sorted((r for r, s in issues.items() if "value" in s and r.startswith(home + "#") and s["value"]["address"] == r
                              and s["value"]["state"] == "open" and not s["value"]["pull_request"]), key=lambda r: int(r.rsplit("#", 1)[1]))
            observations["home_open_issues"] = {"value": listing}

    # Permission lookups: every in-scope repository an issue or the home is in, for every human login
    # the state names. Bots are never looked up (they are trusted only by allowlist).
    table = {k.lower(): v for k, v in state.get("collaborators", {}).items()}
    logins: set[str] = set()
    for it in state["issues"].values():
        if author(it) and it.get("author_type", "User") != "Bot":
            logins.add(author(it))
        for e in it.get("editors", []):
            login, kind = (e.get("login"), e.get("type", "User")) if isinstance(e, dict) else (e, "User")
            if login and kind != "Bot":
                logins.add(login)
    for pr in state.get("prs", []):
        a = pr.get("author") or {}
        if a.get("login") and not a.get("is_bot") and not a["login"].startswith("app/") and not a["login"].endswith("[bot]"):
            logins.add(a["login"])
    repos_seen = sorted({home} | {r.split("#", 1)[0] for r in issues})
    permissions: dict[str, Any] = {}
    for repo in repos_seen:
        if not _in_scope(params, repo):
            continue
        levels = table.get(repo, [])
        levels = levels if isinstance(levels, dict) else {login: "write" for login in levels}
        row: dict[str, Any] = {}
        for login in sorted(logins, key=str.lower):
            if login in levels:
                row[login.lower()] = {"value": levels[login]}
            elif state.get("collaborators_forbidden"):
                row[login.lower()] = {"unavailable": "the permission lookup was refused (HTTP 403)"}
            else:
                row[login.lower()] = {"value": None}
        permissions[repo] = row
    observations["permissions"] = permissions
    if params["trust"]["codeowners"]:
        files = {k.lower(): v for k, v in state.get("codeowners", {}).items()}
        owners_obs: dict[str, Any] = {}
        for repo in repos_seen:
            if not _in_scope(params, repo):
                continue
            if state.get("contents_fail"):
                owners_obs[repo] = {"unavailable": "the contents lookup failed (HTTP 500)"}
                continue
            found = next(({"path": path, "text": files.get(repo, {})[path]} for path in CODEOWNERS_PATHS if path in files.get(repo, {})), None)
            owners_obs[repo] = {"value": found}
        observations["codeowners"] = owners_obs
    return {"bundle": BUNDLE_VERSION, "format": FORMAT, "profile": PROFILE, "parameters": params, "observations": observations}
