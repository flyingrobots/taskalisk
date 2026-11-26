#!/usr/bin/env python3
"""Check the issue-dag/2 conformance corpus against the specification and the Python compiler.

    python3 scripts/corpus/check.py <issue-dag checkout>

Fails (exit 1, one line per problem) when:
- a characterisation case's expected result is not what the compiler computes now (drift);
- a normative case and the compiler disagree and the case records no classified disagreement, or a
  recorded disagreement no longer holds;
- a normative case cites no rule, or any case cites or expects a rule label the specification does
  not state;
- a disagreement has no known classification, names a difference the note does not number, or
  has no characterisation twin `<name>--python`;
- a case directory does not hold exactly its three files;
- a bundle is not valid under corpus/bundle.md, or does not record an observation the run reads;
- the DIGEST file, or the digest named in versions.md, is not the corpus's digest.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import bundle as ob  # noqa: E402
from corpus import digest, forge, spec  # noqa: E402

KINDS = ("characterisation", "normative")
LEVELS = ("document", "graph")
DOCUMENT_RESULTS = ("valid", "invalid", "no-document", "error")
GRAPH_OUTCOMES = ("planned", "invalid", "incomplete", "rejected", "error")
CASE_KEYS = {"id", "level", "kind", "title", "cites", "source"}
CASE_OPTIONAL = {"disagreement", "normative_case"}


def _load(path: pathlib.Path, problems: list[str], name: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        problems.append(f"{name}: {path.name} is missing")
    except json.JSONDecodeError as exc:
        problems.append(f"{name}: {path.name} is not JSON ({exc})")
    return None


def _labels_in(expected: dict[str, Any]) -> list[str]:
    found = list(expected.get("violations", [])) + list(expected.get("warnings", []))
    found += [f["rule"] for f in expected.get("findings", [])]
    return found


def _comparable(key: str, value: Any) -> Any:
    """A member of an expected result as CC6 defines it: findings are a set, compared in a canonical
    order; every other member, such as ready, scores and batch, is compared as written."""
    if key == "findings" and isinstance(value, list):
        return sorted({json.dumps(item, sort_keys=True) for item in value})
    return value


def check_case(level: str, where: pathlib.Path, labels: dict[str, str], diffs: dict[int, str], all_cases: dict[str, dict[str, Any]]) -> list[str]:
    name = f"{level}/{where.name}"
    p: list[str] = []
    wanted = {"case.json", "expected.json", "input.json" if level == "document" else "bundle.json"}
    present = {child.name for child in where.iterdir()}
    for stray in sorted(present - wanted):
        p.append(f"{name}: {stray} is not one of the three files of a case (CC2)")
    for missing_file in sorted(wanted - present):
        p.append(f"{name}: {missing_file} is missing (CC2)")
    if wanted - present:
        return p
    meta = _load(where / "case.json", p, name)
    if not isinstance(meta, dict):
        return p
    missing, extra = CASE_KEYS - set(meta), set(meta) - CASE_KEYS - CASE_OPTIONAL
    if missing or extra:
        p.append(f"{name}: case.json has missing {sorted(missing)} or unknown {sorted(extra)} members (CC2)")
        return p
    if meta["id"] != name or meta["level"] != level:
        p.append(f"{name}: case.json names id {meta['id']!r} and level {meta['level']!r}; the directory says {name} (CC2)")
    if meta["kind"] not in KINDS:
        p.append(f"{name}: kind {meta['kind']!r} is not one of {', '.join(KINDS)} (CC2)")
    cites = meta["cites"] if isinstance(meta["cites"], list) else []
    if meta["kind"] == "normative" and not cites:
        p.append(f"{name}: a normative case cites at least one rule (cites is empty) (CC3)")
    for label in cites:
        if label not in labels:
            p.append(f"{name}: cites {label}, which no document of the specification states (CC3)")
    dis = meta.get("disagreement")
    if dis is not None:
        if not isinstance(dis, dict) or dis.get("classification") not in spec.CLASSIFICATIONS:
            p.append(f"{name}: disagreement classification {(dis or {}).get('classification')!r} is not one of {', '.join(spec.CLASSIFICATIONS)} (CC4)")
        elif "difference" in dis and dis["difference"] not in diffs:
            p.append(f"{name}: disagreement names difference {dis['difference']}, which notes/python-differences.md does not number (CC4)")
        elif "difference" in dis and diffs[dis["difference"]] != dis["classification"]:
            p.append(f"{name}: classifies difference {dis['difference']} as {dis['classification']}; the note says {diffs[dis['difference']]} (CC4)")
        elif "difference" not in dis:
            p.append(f"{name}: a disagreement names its difference in notes/python-differences.md (CC4)")
    twin = meta.get("normative_case")
    if twin is not None:
        other = all_cases.get(twin)
        if meta["kind"] != "characterisation" or other is None or other.get("kind") != "normative" or other.get("disagreement") != dis:
            p.append(f"{name}: normative_case {twin!r} must be a normative case with the same disagreement (CC4)")

    expected = _load(where / "expected.json", p, name)
    if not isinstance(expected, dict):
        if expected is not None or not any("expected.json" in q for q in p):
            p.append(f"{name}: expected.json must be an object (CC5)")
        return p
    for label in _labels_in(expected):
        if label not in labels:
            p.append(f"{name}: expects rule label {label}, which no document of the specification states (CC5)")
    if level == "document":
        given = _load(where / "input.json", p, name)
        if not isinstance(given, dict) or set(given) != {"address", "body"}:
            p.append(f"{name}: input.json is {{\"address\", \"body\"}} (CC2)")
            return p
        if expected.get("result") not in DOCUMENT_RESULTS or (meta["kind"] == "normative" and expected["result"] == "error"):
            p.append(f"{name}: expected result {expected.get('result')!r} is not allowed (CC5)")
        actual = forge.run_document(given["body"], given["address"])
    else:
        before = len(p)
        bundle = _load(where / "bundle.json", p, name)
        if len(p) > before:
            return p
        for problem in ob.validate(bundle):  # rejects null and every other non-object
            p.append(f"{name}: bundle.json: {problem}")
        if p:
            return p
        if expected.get("outcome") not in GRAPH_OUTCOMES or (meta["kind"] == "normative" and expected["outcome"] == "error"):
            p.append(f"{name}: expected outcome {expected.get('outcome')!r} is not allowed (CC5)")
        try:
            actual = forge.run_graph(bundle)
        except forge.BundleIncomplete as exc:
            p.append(f"{name}: bundle.json does not record an observation the run reads: {exc} (OB5)")
            return p
    if meta["kind"] == "characterisation":
        if actual != expected:
            p.append(f"{name}: drift: the compiler now computes {json.dumps(actual, sort_keys=True)[:400]}")
        if dis is not None and twin is None:
            p.append(f"{name}: a characterisation case records a disagreement only as the twin of a normative case (CC4)")
        return p
    differs = sorted(k for k in expected if _comparable(k, expected[k]) != _comparable(k, actual.get(k)))
    if differs and dis is None:
        p.append(f"{name}: unclassified disagreement with the compiler on {', '.join(differs)}: "
                 f"{json.dumps({k: actual.get(k) for k in differs}, sort_keys=True)[:400]}")
    if not differs and dis is not None:
        p.append(f"{name}: records a disagreement, but the compiler no longer disagrees (CC4)")
    return p


def check(spec_root: pathlib.Path) -> list[str]:
    """Every problem of the corpus under `spec_root`/corpus; empty when it passes."""
    spec_root = pathlib.Path(spec_root)
    corpus = spec_root / "corpus"
    problems: list[str] = []
    try:
        labels = spec.rule_labels(spec_root)
    except ValueError as exc:
        return [str(exc)]
    diffs = spec.differences(spec_root)
    for n, classification in diffs.items():
        if classification not in spec.CLASSIFICATIONS:
            problems.append(f"notes/python-differences.md: difference {n} is classified {classification!r} (CC4)")
    actual = digest.corpus_digest(corpus)
    recorded = (corpus / digest.DIGEST_FILE).read_text().strip() if (corpus / digest.DIGEST_FILE).exists() else None
    if recorded != actual:
        problems.append(f"corpus/DIGEST records {recorded!r}; the corpus digests to {actual} (CD1)")
    if actual not in (spec_root / "versions.md").read_text(encoding="utf-8"):
        problems.append(f"versions.md does not name the corpus digest {actual} (N4)")
    all_cases: dict[str, dict[str, Any]] = {}
    for level in LEVELS:
        for meta in sorted((corpus / "cases" / level).glob("*/case.json")):
            try:
                all_cases[f"{level}/{meta.parent.name}"] = json.loads(meta.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
    for case_id, meta in sorted(all_cases.items()):
        if meta.get("kind") == "normative" and "disagreement" in meta:
            twin = all_cases.get(f"{case_id}--python")
            if twin is None or twin.get("normative_case") != case_id:
                problems.append(f"{case_id}: records a disagreement but has no characterisation twin {case_id}--python (CC4)")
            else:
                level, name = case_id.split("/", 1)
                given = "input.json" if level == "document" else "bundle.json"
                try:
                    same = (json.loads((corpus / "cases" / level / name / given).read_text(encoding="utf-8"))
                            == json.loads((corpus / "cases" / level / f"{name}--python" / given).read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    same = False  # a missing or unreadable file is reported by check_case
                if not same:
                    problems.append(f"{case_id}--python: the twin's {given} is not its normative case's input (CC4)")
    for level in LEVELS:
        base = corpus / "cases" / level
        if not base.is_dir():
            problems.append(f"corpus/cases/{level} is missing (CC1)")
            continue
        for where in sorted(d for d in base.iterdir() if d.is_dir()):
            problems += check_case(level, where, labels, diffs, all_cases)
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="check.py", description="Check an issue-dag conformance corpus: every case, "
                                     "every citation and classification, and the recorded digest.")
    parser.add_argument("checkout", help="an issue-dag checkout (or the vendored copy under tests/fixtures/issue-dag)")
    try:
        ns = parser.parse_args(argv)
    except SystemExit as stop:
        return int(stop.code or 0)
    root = pathlib.Path(ns.checkout)
    if not (root / "corpus" / "cases").is_dir():
        sys.stderr.write(f"check.py: {root} is no issue-dag checkout (it has no corpus/cases)\n")
        return 2
    problems = check(root)
    for problem in problems:
        print(problem)
    cases = sum(1 for _ in (pathlib.Path(argv[0]) / "corpus" / "cases").glob("*/*/case.json"))
    print(f"{cases} cases, {len(problems)} problem(s)", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
