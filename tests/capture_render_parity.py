#!/usr/bin/env python3
"""Capture the Python compiler's plan lines for the graph cases of the vendored corpus.

Not a test (unittest discovery skips it). For each graph case of
`tests/fixtures/issue-dag/corpus/cases/graph/` where the Python and the specification agree (no
`--python` twin, and not a twin itself), the bundle is planned by the Python compiler offline
(`scripts/corpus/forge.py`) and its result messages are written as `emit_plan` hands them to the
Parley writer, without the writer's envelope (`t`, `seq`, `run`), one sorted-key JSON object per
line, with `_schema` added from the message's id. A case the Python does not plan (rejected, a
failed observation) gets no fixture. One case is captured twice, the second time with titles that
hold what JSON must escape (TITLED), and a few corpus cases are changed to reach what none does
(VARIANTS).

The Rust renderer (`crates/taskalisk`, flyingrobots/taskalisk#58) is compared with these lines
field by field. `tests/test_render_parity.py` fails when a fixture differs from what this script
would write, so the fixtures are captured output, never hand-written:

    python3 tests/capture_render_parity.py
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "fixtures" / "issue-dag" / "corpus" / "cases" / "graph"
FIXTURES = ROOT / "tests" / "fixtures" / "render"
for path in (ROOT / "scripts", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from corpus import forge  # noqa: E402
from corpus.bundle import TRUST_POLICY  # noqa: E402


class _Run:
    """Collects the result messages emit_plan writes, as the writer receives them."""

    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []

    def result(self, obj: dict[str, Any], schema: Any) -> None:
        schema_id, version = schema
        self.lines.append({**obj, "_schema": {"id": schema_id, "version": version}})

    def error(self, *args: Any, **kwargs: Any) -> None:
        """A parley.error line: the writer's, outside the renderer (the plan line names its code)."""


def agreed_cases() -> list[str]:
    """The graph cases with no `--python` twin, in name order."""
    twinned: set[str] = set()
    names = sorted(p.name for p in CASES.iterdir() if p.is_dir())
    for name in names:
        twin = json.loads((CASES / name / "case.json").read_text()).get("normative_case")
        if twin:
            twinned |= {name, twin.split("/", 1)[1]}
    return [n for n in names if n not in twinned]


# A case planned again with a title on every issue that holds what JSON must escape: DEL and the C0
# controls, Latin-1, an astral character, a line separator, a quote and a backslash. The bundle has no
# titles (the forge answers "(title not recorded)"), so the forge is given these instead. The fixture
# is named `<case>--titles`.
TITLED = "discovery-unmodeled-home-issue"
TITLED_SUFFIX = "--titles"


def hostile_title(number: int) -> str:
    return f"T{number} \x7f\x00\x01\x1f\t\n\r\b\f é 😀 \u2028 \" \\ / end"


class _Titled(forge.BundleForge):
    def rest_issue(self, ref: str) -> dict[str, Any]:
        obj = super().rest_issue(ref)
        obj["title"] = hostile_title(obj["number"])
        return obj


# Corpus cases changed to reach what no case does, each planned from its changed bundle, which is
# written beside the fixtures (`bundles/<name>.json`) so that the Rust test plans the same input.
def _opaque_child(bundle: dict[str, Any]) -> dict[str, Any]:
    """d9-container with its child o/s#2 given a plain body, and o/r#1 waiting on it: an opaque
    issue that a container and a task name, which 1.x lists in the order it read them (the
    container first, though `o/r#1` sorts before `o/r#9`)."""
    issues = bundle["observations"]["issues"]
    issues["o/s#2"]["value"]["body"]["value"]["text"] = "A plain body.\n"
    one = issues["o/r#1"]["value"]["body"]["value"]
    one["text"] = one["text"].replace(".blocked_by: []", ".blocked_by: [o/s#2]")
    return bundle


VARIANTS = {"d9-container--opaque-child": ("d9-container", _opaque_child)}


def bundle_of(name: str) -> dict[str, Any]:
    """The bundle a fixture plans: a corpus case's, or a variant's."""
    if name in VARIANTS:
        case, change = VARIANTS[name]
        return change(json.loads((CASES / case / "bundle.json").read_text()))
    return json.loads((CASES / name / "bundle.json").read_text())


def bundle_text(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def python_lines(name: str, titled: bool = False) -> list[dict[str, Any]] | None:
    """The Python's result messages for one case, or None when it does not plan it."""
    bundle = bundle_of(name)
    if bundle["parameters"]["trust"]["policy"] != TRUST_POLICY:
        return None
    if titled:
        saved, forge.BundleForge = forge.BundleForge, _Titled
        try:
            out = forge.compile_bundle(bundle)
        finally:
            forge.BundleForge = saved
    else:
        out = forge.compile_bundle(bundle)
    if out.result is None:
        return None
    run = _Run()
    forge.compiler().emit_plan(run, out.result, "github", out.failures, None, None, out.rel_failed)
    return run.lines


def fixture_text(lines: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(line, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for line in lines)


def expected_fixtures() -> dict[str, str]:
    """{case name: fixture text} for every case the Python plans."""
    out = {}
    for name in agreed_cases():
        lines = python_lines(name)
        if lines is not None:
            out[name] = fixture_text(lines)
    titled = python_lines(TITLED, titled=True)
    if titled is not None:
        out[TITLED + TITLED_SUFFIX] = fixture_text(titled)
    for name in VARIANTS:
        lines = python_lines(name)
        if lines is not None:
            out[name] = fixture_text(lines)
    return out


def expected_bundles() -> dict[str, str]:
    """{variant name: its bundle's text}."""
    return {name: bundle_text(bundle_of(name)) for name in VARIANTS}


def main() -> int:
    target = FIXTURES / "python"
    target.mkdir(parents=True, exist_ok=True)
    expected = expected_fixtures()
    for stale in target.glob("*.jsonl"):
        if stale.stem not in expected:
            stale.unlink()
    for name, text in expected.items():
        (target / f"{name}.jsonl").write_text(text)
    bundles = FIXTURES / "bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    for name, text in expected_bundles().items():
        (bundles / f"{name}.json").write_text(text)
    print(json.dumps({"event": "captured", "cases": len(expected)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
