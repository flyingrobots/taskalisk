#!/usr/bin/env python3
"""Write the issue-dag/2 conformance corpus into a checkout of the specification repository.

    python3 scripts/corpus/generate.py <issue-dag checkout> [--vendor <directory>]

Writes corpus/cases/ from scripts/corpus/cases.py, recomputes corpus/DIGEST, and names the digest
in versions.md. Normative cases are written as their definitions state them. Characterisation
cases take their expected result from the Python compiler in this checkout. Every normative case
that records a disagreement gets a characterisation twin, `<name>--python`, holding what the
compiler computes for the same input.

--vendor also copies the specification and the corpus to <directory> (tests/fixtures/issue-dag),
the copy this repository's offline tests check.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import sys
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import cases, digest, forge  # noqa: E402

VENDORED = ("README.md", "versions.md", "formats", "profiles", "contracts", "notes", "corpus")
CORPUS_ROW = re.compile(r"^(\| \[`corpus/`\].*?)`sha256:[0-9a-f]{64}`(.*)$", re.M)


def dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _write_case(base: pathlib.Path, level: str, name: str, meta: dict[str, Any], inputs: dict[str, Any], expected: dict[str, Any]) -> None:
    where = base / level / name
    where.mkdir(parents=True)
    full = {"id": f"{level}/{name}", "level": level, **meta}
    (where / "case.json").write_text(dump(full), encoding="utf-8")
    for filename, value in inputs.items():
        (where / filename).write_text(dump(value), encoding="utf-8")
    (where / "expected.json").write_text(dump(expected), encoding="utf-8")


def _meta(kind: str, case: Any, **extra: Any) -> dict[str, Any]:
    meta = {"kind": kind, "title": case.title, "cites": list(case.cites), "source": case.source}
    if case.disagreement is not None:
        meta["disagreement"] = dict(case.disagreement)
    meta.update(extra)
    return meta


def write_cases(corpus: pathlib.Path) -> dict[str, int]:
    base = corpus / "cases"
    if base.exists():
        shutil.rmtree(base)
    counts = {"document normative": 0, "document characterisation": 0, "graph normative": 0, "graph characterisation": 0}
    for doc in cases.NORMATIVE_DOCUMENTS:
        inputs = {"input.json": {"address": doc.address, "body": doc.body}}
        _write_case(base, "document", doc.name, _meta("normative", doc), inputs, doc.expected)
        counts["document normative"] += 1
        if doc.disagreement is not None:
            twin = _meta("characterisation", doc, normative_case=f"document/{doc.name}")
            twin["title"] = f"What the compiler does: {doc.title}"
            twin["source"] = f"the Python compiler, on the input of document/{doc.name}"
            _write_case(base, "document", f"{doc.name}--python", twin, inputs, forge.run_document(doc.body, doc.address))
            counts["document characterisation"] += 1
    for doc in cases.CENSUS:
        inputs = {"input.json": {"address": doc.address, "body": doc.body}}
        _write_case(base, "document", doc.name, _meta("characterisation", doc), inputs, forge.run_document(doc.body, doc.address))
        counts["document characterisation"] += 1
    for graph in cases.NORMATIVE_GRAPHS:
        inputs = {"bundle.json": graph.bundle}
        _write_case(base, "graph", graph.name, _meta("normative", graph), inputs, graph.expected)
        counts["graph normative"] += 1
        if graph.disagreement is not None:
            twin = _meta("characterisation", graph, normative_case=f"graph/{graph.name}")
            twin["title"] = f"What the compiler does: {graph.title}"
            twin["source"] = f"the Python compiler, on the bundle of graph/{graph.name}"
            _write_case(base, "graph", f"{graph.name}--python", twin, inputs, forge.run_graph(graph.bundle))
            counts["graph characterisation"] += 1
    for graph in cases.SCENARIOS:
        _write_case(base, "graph", graph.name, _meta("characterisation", graph), {"bundle.json": graph.bundle}, forge.run_graph(graph.bundle))
        counts["graph characterisation"] += 1
    return counts


def write(spec_root: pathlib.Path) -> dict[str, int]:
    """Write the cases, the DIGEST and the digest in versions.md under `spec_root`."""
    spec_root = pathlib.Path(spec_root)
    corpus = spec_root / "corpus"
    counts = write_cases(corpus)
    value = digest.corpus_digest(corpus)
    (corpus / digest.DIGEST_FILE).write_text(value + "\n", encoding="utf-8")
    versions = spec_root / "versions.md"
    text = versions.read_text(encoding="utf-8")
    updated = CORPUS_ROW.sub(lambda m: f"{m.group(1)}`{value}`{m.group(2)}", text)
    if updated != text:
        versions.write_text(updated, encoding="utf-8")
    return counts


def vendor(spec_root: pathlib.Path, target: pathlib.Path) -> None:
    """Copy the parts of the specification the checker reads, and the corpus, to `target`."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in VENDORED:
        src = spec_root / name
        if src.is_dir():
            shutil.copytree(src, target / name)
        else:
            shutil.copy2(src, target / name)


def main(argv: list[str]) -> int:
    if not argv or len(argv) not in (1, 3) or (len(argv) == 3 and argv[1] != "--vendor"):
        sys.stderr.write("usage: generate.py <issue-dag checkout> [--vendor <directory>]\n")
        return 2
    spec_root = pathlib.Path(argv[0])
    counts = write(spec_root)
    for key, n in counts.items():
        print(f"{n:4d} {key}")
    print((spec_root / "corpus" / digest.DIGEST_FILE).read_text().strip())
    if len(argv) == 3:
        vendor(spec_root, pathlib.Path(argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
