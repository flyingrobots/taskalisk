"""Read Taskalisk's Parley output in tests: parse the streams, validate every line, and rebuild the
1.x single document from the lines (the golden reconstruction).

`reconstruct` is the proof that the lines carry everything the old document did: it may only read
lines, and it must give back the document the 1.x compiler printed for the same backlog.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "taskalisk" / "scripts"
SCHEMA_DIR = ROOT / "skills" / "taskalisk" / "schemas"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import parley_emit as pe  # noqa: E402  (the vendored writer and its bounded checker)

ENVELOPE = ("event", "t", "seq", "run", "_schema")


def tool_schemas(directory=SCHEMA_DIR):
    """{(id, version): schema} for every schema directly under `directory` (not recursive)."""
    out = {}
    for path in sorted(directory.glob("*.schema.json")):
        doc = json.loads(path.read_text())
        props = doc["properties"]["_schema"]["properties"]
        out[(props["id"]["const"], props["version"]["const"])] = doc
    return out


# The schemas of the lines the Python writes (and the binary, under the same contract).
TOOL_SCHEMAS = tool_schemas()
# Decision D22: the schemas only the Rust binary writes, in schemas/binary/, until the cutover (#32).
BINARY_SCHEMAS = tool_schemas(SCHEMA_DIR / "binary")
# Every Taskalisk schema: what a line from either implementation is validated against.
ALL_SCHEMAS = {**TOOL_SCHEMAS, **BINARY_SCHEMAS}


def parse(text, stream):
    """Every line of a stream as a JSON object; anything else is a contract failure."""
    lines = []
    # split on "\n" only: str.splitlines() also breaks on U+0085, U+2028 and U+2029, which may sit inside a JSON string
    for n, raw in enumerate(text.removesuffix("\n").split("\n") if text else [], 1):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"{stream} line {n} is not JSON ({exc}): {raw[:300]!r}")
        if not isinstance(obj, dict):
            raise AssertionError(f"{stream} line {n} is not a JSON object: {raw[:300]!r}")
        lines.append(obj)
    if text and not text.endswith("\n"):
        raise AssertionError(f"{stream} ends without a newline")
    return lines


def problems(lines):
    """Lines that do not validate against the exact schema their _schema names (OUT-01)."""
    bad = []
    for line in lines:
        result = pe.validate_line(line, TOOL_SCHEMAS)
        if not result.ok:
            bad.append((line.get("_schema"), line.get("event"), result.errors or result.unsupported))
    return bad


def receipt_lines(out_lines, cwd=None):
    """The receipt the bootstrap line names, parsed; a sidecar event is replaced by the record it holds."""
    boot = out_lines[0]
    path = pathlib.Path(boot["paths"]["receipt"])
    lines = parse(path.read_text(), "receipt")
    resolved = []
    for line in lines:
        if line.get("event") == "sidecar":
            resolved.append(json.loads((path.parent / line["path"]).read_text()))
        else:
            resolved.append(line)
    return resolved


def sid(line):
    return line.get("_schema", {}).get("id")


def of(lines, schema_id):
    return [l for l in lines if sid(l) == schema_id]


def one(lines, schema_id):
    found = of(lines, schema_id)
    return found[0] if found else None


def payload(line, drop=()):
    return {k: v for k, v in line.items() if k not in ENVELOPE and k not in drop}


def findings(lines, code):
    return [l for l in of(lines, "taskalisk.finding") if l["code"] == code]


def details(lines, code):
    return [f["detail"] for f in findings(lines, code)]


def grouped(lines, code):
    out = {}
    for f in findings(lines, code):
        out.setdefault(f["subject"], []).append(f["message"])
    return out


def gh_errors(err_lines, phase=None):
    return [{"source": e["detail"]["source"], "error": e["detail"]["error"]} for e in of(err_lines, "parley.error")
            if isinstance(e.get("detail"), dict) and "source" in e["detail"] and (phase is None or e["detail"].get("phase") == phase)]


def error_problem(err_lines, *codes):
    for e in of(err_lines, "parley.error"):
        if e["code"] in codes:
            return e["problem"]
    return None


NO_PLAN_SUMMARY = {"discovery": "GitHub inventory failed; refusing to compile a partial graph",
                   "edge_edit": "Frontmatter edit failed"}


def reconstruct(out, err):
    """The 1.x document, rebuilt from the lines of one run."""
    if one(out, "taskalisk.inventory.summary"):
        return reconstruct_inventory(out, err)
    plan = one(out, "taskalisk.plan")
    edit = one(out, "taskalisk.edge_edit")
    mutation = payload(edit) if edit else None
    if plan is None:
        for code in ("dag_spec.unreadable", "dag_spec.invalid"):
            problem = error_problem(err, code)
            if problem:
                return {"ok": False, "error": problem}
        gh = of(err, "parley.error")
        phase = next((e["detail"].get("phase") for e in gh if isinstance(e.get("detail"), dict) and e["detail"].get("phase")), "discovery")
        doc = {"ok": False, "error": NO_PLAN_SUMMARY[phase], "github_errors": gh_errors(err)}
        if phase == "discovery":
            doc["mutation"] = mutation
        return doc

    doc = {"ok": plan["ok"]}
    outcome = plan["outcome"]
    redundant = details(out, "edge.redundant")
    soft = details(out, "edge.soft_or_low_confidence")
    if outcome == "compiled":
        waves = {}
        ranked = [payload(n, ("rank", "wave", "score")) for n in of(out, "taskalisk.frontier_node")]
        by_id = {n["id"]: n for n in ranked}
        by_id.update({n["id"]: payload(n, ("wave",)) for n in of(out, "taskalisk.node")})
        for w in of(out, "taskalisk.wave"):
            waves[w["label"]] = [by_id[i] for i in w["ids"]]
        batch = one(out, "taskalisk.batch")
        doc.update({
            "metrics": plan["metrics"],
            "edges": [payload(e) for e in of(out, "taskalisk.edge")],
            "transitive_redundant_edges_removed": redundant,
            "soft_or_low_confidence_edges": soft,
            "unknown_dependencies": [],
            "stale_merged_hints": [],
            "open_frontier_count": plan["open_frontier_count"],
            "open_frontier_ranked": ranked,
            "conflict_free_frontier_batch": batch["members"],
            "batch_skipped": batch["skipped"],
            "semaphores_with_unknown_capacity_treated_as_1": batch["semaphores_with_unknown_capacity_treated_as_1"],
            "waves": waves,
        })
    elif outcome == "cycle":
        doc.update({"error": error_problem(err, "graph.cycle"), "cyclic_nodes": [f["subject"] for f in findings(out, "graph.cyclic_node")],
                    "unknown_dependencies": [], "stale_merged_hints": []})
    else:
        doc.update({"error": error_problem(err, "graph.unresolved_prerequisites"),
                    "unknown_dependencies": details(out, "prerequisite.unknown"),
                    "stale_merged_hints": details(out, "prerequisite.stale_merged_hint"),
                    "soft_or_low_confidence_edges": soft})
    if plan["mode"] == "github":
        src = plan["source"]
        doc["source"] = {
            **src,
            "containers_excluded": details(out, "container.excluded"),
            "unmodeled_open_issues": details(out, "issue.unmodeled"),
            "untrusted_issues": details(out, "issue.untrusted"),
            "untrusted_linked_prs": details(out, "pull_request.untrusted"),
            "opaque_nodes": details(out, "issue.opaque"),
            "not_planned_parents": details(out, "parent.not_planned"),
        }
        doc["frontmatter"] = {"violating_issues": plan["violating_issues"],
                              "violations": grouped(out, "frontmatter.violation"),
                              "warnings": grouped(out, "frontmatter.warning")}
        if outcome == "compiled" and not plan["ok"] and error_problem(err, "frontmatter.invalid"):
            doc["error"] = error_problem(err, "frontmatter.invalid")
        rel = plan.get("relationships") or {}
        if rel.get("compared") and rel.get("in_sync") is not None:
            doc["relationship_drift"] = {
                "only_in_frontmatter": [f"{d['from']} -> {d['to']}" for d in details(out, "relationship.only_in_frontmatter")],
                "only_in_github": [f"{d['from']} -> {d['to']}" for d in details(out, "relationship.only_in_github")],
                "in_sync": rel["in_sync"]}
        rel_errors = gh_errors(err, "relationships")
        if rel_errors:
            doc["ok"] = False
            doc["error"] = "GitHub relationship lookup failed"
            doc["github_errors"] = rel_errors
        if mutation is not None:
            doc["mutation"] = mutation
    doc["meta"] = {"artifact_hash": plan["artifact_hash"]}
    return doc


def reconstruct_inventory(out, err):
    summary = one(out, "taskalisk.inventory.summary")
    branches = of(out, "taskalisk.inventory.branch")
    return {
        "ok": summary["ok"],
        "worktrees": [payload(w) for w in of(out, "taskalisk.inventory.worktree")],
        "unmerged_branches": {scope: [payload(b, ("scope",)) for b in branches if b["scope"] == scope] for scope in ("local", "remote")},
        "github": {"open_prs": [payload(p) for p in of(out, "taskalisk.inventory.pull_request")],
                   "open_issues": [payload(i) for i in of(out, "taskalisk.inventory.issue")]},
        "inventory_errors": gh_errors(err),
    }


def rendering(out, fmt):
    line = next((l for l in of(out, "taskalisk.rendering") if l["format"] == fmt), None)
    return None if line is None else line["text"]
