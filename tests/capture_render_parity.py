#!/usr/bin/env python3
"""Capture the Python compiler's plan lines for the graph cases of the vendored corpus.

Not a test (unittest discovery skips it). For each graph case of
`tests/fixtures/issue-dag/corpus/cases/graph/` where the Python and the specification agree (no
`--python` twin, and not a twin itself), the bundle is planned by the Python compiler offline
(`scripts/corpus/forge.py`) and its result messages are written as `emit_plan` hands them to the
Parley writer, without the writer's envelope (`t`, `seq`, `run`), one sorted-key JSON object per
line, with `_schema` added from the message's id. A case the Python does not plan (rejected, a
failed observation, a bundle that lacks a slot the run reads) gets no fixture. One case is captured twice, the second time with titles that
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


def _opaque_children(bundle: dict[str, Any]) -> dict[str, Any]:
    """d9-container with `.children: [o/s#2, o/r#1]`, both with plain bodies: two opaque issues,
    which 1.x lists in the order it read them (o/s#2 first, though o/r#1 sorts first)."""
    issues = bundle["observations"]["issues"]
    nine = issues["o/r#9"]["value"]["body"]["value"]
    nine["text"] = nine["text"].replace(".children: [o/r#1, o/s#2]", ".children: [o/s#2, o/r#1]")
    for ref in ("o/s#2", "o/r#1"):
        issues[ref]["value"]["body"]["value"]["text"] = "A plain body.\n"
    return bundle


def _issue(bundle: dict[str, Any], ref: str, body: str, state: str = "open", reason: str | None = None) -> None:
    """Adds an issue like the bundle's o/r#1, at another address, with this body."""
    entry = json.loads(json.dumps(bundle["observations"]["issues"]["o/r#1"]))
    value = entry["value"]
    value.update({"address": ref, "state": state, "state_reason": reason})
    value["body"]["value"]["text"] = body
    bundle["observations"]["issues"][ref] = entry


def _doc(ref: str, kind: str, key: str, refs: list[str]) -> str:
    extra = ".type: feature\n" if kind == "task" else ""
    return f"```yaml\n.dag: issue-dag/2\n.id: {ref}\n.kind: {kind}\n{extra}{key}: [{', '.join(refs)}]\n```\n"


def _traversal(bundle: dict[str, Any]) -> dict[str, Any]:
    """Every list 1.x writes in the order it read the issues, each read out of sorted order: the
    root container o/r#9 names the container o/s#2 before the container o/r#1; o/s#2 names the
    task o/r#30, o/r#1 the task o/r#4 and the plain o/r#20 and o/r#10; o/r#30 waits on o/r#7 and
    then o/r#5, both closed as not planned."""
    issues = bundle["observations"]["issues"]
    issues["o/r#9"]["value"]["body"]["value"]["text"] = _doc("o/r#9", "container", ".children", ["o/s#2", "o/r#1"])
    issues["o/s#2"]["value"]["body"]["value"]["text"] = _doc("o/s#2", "container", ".children", ["o/r#30"])
    issues["o/r#1"]["value"]["body"]["value"]["text"] = _doc("o/r#1", "container", ".children", ["o/r#4", "o/r#20", "o/r#10"])
    _issue(bundle, "o/r#30", _doc("o/r#30", "task", ".blocked_by", ["o/r#7", "o/r#5"]))
    _issue(bundle, "o/r#4", _doc("o/r#4", "task", ".blocked_by", []))
    _issue(bundle, "o/r#20", "A plain body.\n")
    _issue(bundle, "o/r#10", "A plain body.\n")
    for ref in ("o/r#7", "o/r#5"):
        _issue(bundle, ref, _doc(ref, "task", ".blocked_by", []), state="closed", reason="not_planned")
    return bundle


def _not_planned_read_first(bundle: dict[str, Any]) -> dict[str, Any]:
    """The traversal variant with o/r#1 naming o/r#5 first, so o/r#5 is read before o/r#7: 1.x
    still lists o/r#30's not-planned prerequisites in its `.blocked_by` order, o/r#7 then o/r#5."""
    bundle = _traversal(bundle)
    one = bundle["observations"]["issues"]["o/r#1"]["value"]["body"]["value"]
    one["text"] = _doc("o/r#1", "container", ".children", ["o/r#5", "o/r#4", "o/r#20", "o/r#10"])
    return bundle


def _not_planned_per_task(bundle: dict[str, Any]) -> dict[str, Any]:
    """The traversal variant with o/r#4 waiting on [o/r#5, o/r#7] while o/r#30 waits on
    [o/r#7, o/r#5]: 1.x lists each task's not-planned prerequisites in that task's own order."""
    bundle = _traversal(bundle)
    four = bundle["observations"]["issues"]["o/r#4"]["value"]["body"]["value"]
    four["text"] = _doc("o/r#4", "task", ".blocked_by", ["o/r#5", "o/r#7"])
    return bundle


def _unknown_and_cycle(bundle: dict[str, Any]) -> dict[str, Any]:
    """graph-cycle with flyingrobots/geordi#1 also waiting on x/y#1, outside the read scope: an
    unknown prerequisite (X3) and a cycle (G4) in one run. 1.x checks the prerequisites first, so
    the plan is `unresolved`, not `cycle`."""
    one = bundle["observations"]["issues"]["flyingrobots/geordi#1"]["value"]["body"]["value"]
    one["text"] = one["text"].replace(".blocked_by: [flyingrobots/echo#5]", ".blocked_by: [flyingrobots/echo#5, x/y#1]")
    return bundle


def _unknown_in_declared_order(bundle: dict[str, Any]) -> dict[str, Any]:
    """d9-container with o/r#1 waiting on [x/y#20, x/y#3] and o/s#2 on [x/y#9, x/y#1], all outside
    the read scope: 1.x lists unknown prerequisites by task (as text), then in the task's declared
    order, not sorted by reference."""
    issues = bundle["observations"]["issues"]
    for ref, refs in (("o/r#1", ["x/y#20", "x/y#3"]), ("o/s#2", ["x/y#9", "x/y#1"])):
        issues[ref]["value"]["body"]["value"]["text"] = _doc(ref, "task", ".blocked_by", refs)
    return bundle


def _untrusted_in_order_read(bundle: dict[str, Any]) -> dict[str, Any]:
    """d9-container whose root names o/r#40 before o/r#30, both by a stranger: 1.x lists the
    untrusted issues in the order it read them, o/r#40 first, though o/r#30 sorts first."""
    issues = bundle["observations"]["issues"]
    issues["o/r#9"]["value"]["body"]["value"]["text"] = _doc("o/r#9", "container", ".children", ["o/r#40", "o/r#30"])
    for ref in ("o/r#40", "o/r#30"):
        _issue(bundle, ref, _doc(ref, "task", ".blocked_by", []))
        value = issues[ref]["value"]
        value["author"] = {"login": "mallory", "type": "User"}
        value["author_association"] = "NONE"
        value["body"]["value"]["editors"] = [{"login": "mallory", "type": "User"}]
    bundle["observations"]["permissions"].setdefault("o/r", {})["mallory"] = {"value": None}
    return bundle


def _two_strangers(bundle: dict[str, Any]) -> dict[str, Any]:
    """trust-pull-request-by-stranger with a second stranger's pull request, number 9, listed
    before number 8: 1.x lists untrusted pull requests in the order GitHub listed them."""
    pulls = bundle["observations"]["home_open_pull_requests"]["value"]
    nine = json.loads(json.dumps(pulls[0]))
    nine["number"] = 9
    pulls.insert(0, nine)
    return bundle


def _unmodeled_and_cycle(bundle: dict[str, Any]) -> dict[str, Any]:
    """discovery-unmodeled-home-issue with flyingrobots/echo#5 also waiting on
    flyingrobots/geordi#2: a three-issue cycle (echo#5, geordi#1, geordi#2) with echo#6 behind it,
    in a run that also reads a container, an opaque issue and an unmodeled one. 1.x still lists
    what discovery read (decision D13)."""
    five = bundle["observations"]["issues"]["flyingrobots/echo#5"]["value"]["body"]["value"]
    five["text"] = five["text"].replace(".blocked_by: [flyingrobots/bunny#7]", ".blocked_by: [flyingrobots/bunny#7, flyingrobots/geordi#2]")
    return bundle


def _stranger_and_unknown(bundle: dict[str, Any]) -> dict[str, Any]:
    """trust-pull-request-by-stranger with flyingrobots/geordi#110 also waiting on x/y#1, outside the
    read scope: an unknown prerequisite in a run that also lists a stranger's pull request."""
    one = bundle["observations"]["issues"]["flyingrobots/geordi#110"]["value"]["body"]["value"]
    one["text"] = one["text"].replace(".blocked_by: [flyingrobots/bunny#110]", ".blocked_by: [flyingrobots/bunny#110, x/y#1]")
    return bundle


def _traversal_and_cycle(bundle: dict[str, Any]) -> dict[str, Any]:
    """The traversal variant with o/r#4 and o/r#30 waiting on each other: a cycle in a run that
    lists containers, opaque issues and not-planned prerequisites read out of sorted order."""
    bundle = _traversal(bundle)
    issues = bundle["observations"]["issues"]
    issues["o/r#4"]["value"]["body"]["value"]["text"] = _doc("o/r#4", "task", ".blocked_by", ["o/r#30"])
    issues["o/r#30"]["value"]["body"]["value"]["text"] = _doc("o/r#30", "task", ".blocked_by", ["o/r#7", "o/r#5", "o/r#4"])
    return bundle


def _untrusted_and_unknown(bundle: dict[str, Any]) -> dict[str, Any]:
    """The untrusted variant whose root also names o/r#1, which waits on x/y#1, outside the read
    scope: an unknown prerequisite in a run that lists untrusted issues in the order read."""
    bundle = _untrusted_in_order_read(bundle)
    issues = bundle["observations"]["issues"]
    issues["o/r#9"]["value"]["body"]["value"]["text"] = _doc("o/r#9", "container", ".children", ["o/r#40", "o/r#30", "o/r#1"])
    issues["o/r#1"]["value"]["body"]["value"]["text"] = _doc("o/r#1", "task", ".blocked_by", ["x/y#1"])
    return bundle


VARIANTS = {
    "discovery-unmodeled-home-issue--three-issue-cycle": ("discovery-unmodeled-home-issue", _unmodeled_and_cycle),
    "trust-pull-request-by-stranger--unknown-prerequisite": ("trust-pull-request-by-stranger", _stranger_and_unknown),
    "d9-container--traversal-order-and-cycle": ("d9-container", _traversal_and_cycle),
    "d9-container--untrusted-and-unknown": ("d9-container", _untrusted_and_unknown),
    "trust-pull-request-by-stranger--two-in-order-listed": ("trust-pull-request-by-stranger", _two_strangers),
    "d9-container--traversal-order": ("d9-container", _traversal),
    "d9-container--not-planned-in-blocked-by-order": ("d9-container", _not_planned_read_first),
    "d9-container--untrusted-in-order-read": ("d9-container", _untrusted_in_order_read),
    "d9-container--not-planned-per-task-order": ("d9-container", _not_planned_per_task),
    "graph-cycle--and-unknown-prerequisite": ("graph-cycle", _unknown_and_cycle),
    "d9-container--unknown-in-declared-order": ("d9-container", _unknown_in_declared_order),
    "d9-container--opaque-child": ("d9-container", _opaque_child),
    "d9-container--opaque-children-in-order-read": ("d9-container", _opaque_children),
}


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
        try:
            out = forge.compile_bundle(bundle)
        except forge.BundleIncomplete:
            # A bundle that lacks a slot the run reads is unusable evidence (OB5, OB16): no plan.
            return None
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
        # A variant exists to reach something: one that stops giving a plan must fail loudly.
        if lines is None:
            raise AssertionError(f"the variant {name} gives no plan")
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
