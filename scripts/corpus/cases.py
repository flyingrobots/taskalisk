"""The cases of the issue-dag/2 conformance corpus.

Three sources:

- NORMATIVE_DOCUMENTS and NORMATIVE_GRAPHS: an input and the result the specification's rules give
  for it, written by hand from the rule text, never by running the compiler. Each cites its rules.
  Where the compiler disagrees, the case records the classified difference, and the generator adds a
  characterisation twin that records what the compiler does.
- CENSUS: one body per shape of the census of 2026-11-12 (evidence/2026-11-12-frontmatter-shapes.md).
- SCENARIOS: the backlogs of the compiler's own offline tests (tests/test_taskalisk.py) and golden
  scenarios (tests/golden_scenarios.py), recorded as bundles.

Characterisation cases take their expected result from the compiler (scripts/corpus/generate.py).
"""
from __future__ import annotations

import copy
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

TESTS = pathlib.Path(__file__).resolve().parents[2] / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import golden_scenarios as golden  # noqa: E402
from test_taskalisk import BUNNY, ECHO, HOME, STRANGER, closing, fm, issue, plan_state  # noqa: E402

from corpus import bundle as ob  # noqa: E402


@dataclass
class Doc:
    name: str
    title: str
    body: str
    expected: dict[str, Any] | None  # None: characterisation, from the compiler
    cites: list[str] = field(default_factory=list)
    address: str = "o/r#1"
    disagreement: dict[str, Any] | None = None
    source: str = "constructed from the rule text"


@dataclass
class Graph:
    name: str
    title: str
    bundle: dict[str, Any]
    expected: dict[str, Any] | None
    cites: list[str] = field(default_factory=list)
    disagreement: dict[str, Any] | None = None
    source: str = "constructed from the rule text"


def defect(n: int, note: str) -> dict[str, Any]:
    return {"classification": "defect", "difference": n, "note": note}


def exception(n: int, note: str) -> dict[str, Any]:
    return {"classification": "compatibility-exception", "difference": n, "note": note}


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #

BASE = [".dag: issue-dag/2", ".id: o/r#1", ".kind: task", ".type: feature", ".blocked_by: []"]
CONTAINER = [".dag: issue-dag/2", ".id: o/r#1", ".kind: container", ".children: [o/r#2]"]


def block(lines: list[str], before: str = "", after: str = "\n\nFree text.\n", nl: str = "\n", info: str = "```yaml") -> str:
    return before + info + nl + nl.join(lines) + nl + "```" + after


def with_(lines: list[str], *extra: str, drop: tuple[str, ...] = ()) -> list[str]:
    kept = [ln for ln in lines if not any(ln.startswith(d) for d in drop)]
    return kept + list(extra)


def rec(id_: str = "o/r#1", kind: str = "task", type_: str | None = "feature", blocked_by: list[str] | None = None,
        children: list[str] | None = None, size: int | None = None, holds: list[str] | None = None,
        meters: list[list[Any]] | None = None, status: str | None = None) -> dict[str, Any]:
    task = kind == "task"
    return {"version": "issue-dag/2", "id": id_, "kind": kind, "type": type_,
            "blocked_by": (blocked_by or []) if task else None, "children": None if task else (children or []),
            "size_hours": size, "holds": sorted(set(holds or [])), "meters": meters or [], "status": status}


def valid(record: dict[str, Any] | None = None, warnings: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"result": "valid", "record": record or rec(), "warnings": list(warnings)}


def invalid(*labels: str) -> dict[str, Any]:
    return {"result": "invalid", "violations": sorted(set(labels))}


NODOC = {"result": "no-document"}
TASK = valid(rec())
CONTAINER_REC = valid(rec(kind="container", type_=None, children=["o/r#2"]))

D = Doc
NORMATIVE_DOCUMENTS: list[Doc] = [
    # Carrier: C1 to C10
    D("c1-fence-at-start", "A block at the very start of the body is found", block(BASE), TASK, ["C1", "C2", "M4"]),
    D("c1-blank-lines-before-fence", "SP, HT, CR and LF may precede the opening fence", block(BASE, before=" \t\r\n\n"), TASK, ["C1"]),
    D("c1-text-before-fence", "Any other text before the fence means no frontmatter", block(BASE, before="Intro\n"), NODOC, ["C1", "C3"]),
    D("c1-blanks-after-info-string", "Blanks may follow `yaml` on the opening fence", block(BASE, info="```yaml \t"), TASK, ["C1"]),
    D("c1-other-info-string", "An info string other than `yaml` opens no block", block(BASE, info="```yml"), NODOC, ["C1", "C3"]),
    D("c1-info-string-with-more", "Text after `yaml` on the fence opens no block", block(BASE, info="```yaml title"), NODOC, ["C1", "C3"]),
    D("c1-nbsp-before-fence", "U+00A0 before the fence is an ordinary character: no frontmatter", block(BASE, before=" "), NODOC, ["C1", "C3"],
      disagreement=defect(5, "the compiler skips any Unicode white space before the fence")),
    D("c4-crlf-line-ends", "CR LF is a line end throughout", block(BASE, nl="\r\n", after="\r\n\r\nFree text.\r\n"), TASK, ["C1", "C2", "C4"]),
    D("c2-no-closing-fence", "Without a closing fence the body has no frontmatter", "```yaml\n" + "\n".join(BASE) + "\n", NODOC, ["C2", "C3"]),
    D("c2-closing-fence-trailing-blanks", "A closing fence may end in blanks", block(BASE, after=" \t\nFree text.\n"), TASK, ["C2"]),
    D("c2-closing-fence-ends-the-body", "A closing fence may end the body", block(BASE, after=""), TASK, ["C2"]),
    D("c2-fence-with-info-is-not-closing", "A fence line with text after it does not close the block", block(BASE, after="js\n"), NODOC, ["C2", "C3"]),
    D("c2-indented-fence-is-not-closing", "An indented fence does not close the block; a later one does",
      "```yaml\n" + "\n".join(BASE) + "\n  ```\n```\n", invalid("C6"), ["C2", "C6"]),
    D("c2-first-closing-fence-wins", "The block ends at the first closing fence", block(BASE, after="\n.bogus: 1\n```\n"), TASK, ["C2"]),
    D("c2-immediate-fence-alone", "An opening fence followed at once by a fence, with no later fence: no frontmatter", "```yaml\n```\n", NODOC, ["C2", "C3"]),
    D("c2-immediate-fence-then-more", "A fence right after the opening fence is the block's first line when a later fence exists",
      "```yaml\n```\n" + "\n".join(BASE) + "\n```\n", invalid("C6"), ["C2", "C6"]),
    D("c4-lone-cr", "A CR not followed by LF makes the document invalid",
      block(BASE[:3] + [".type: feature\r.size_hours: 2", ".blocked_by: []"]), invalid("C4"), ["C4"],
      disagreement=defect(4, "the compiler splits the line at the CR and reads two valid entries")),
    D("c4-line-separator", "U+2028 inside the block makes the document invalid", block(with_(BASE, "area: a b")), invalid("C4"), ["C4"],
      disagreement=defect(4, "the compiler splits the line at U+2028 and reads `b` as a line of another form")),
    D("c4-vertical-tab", "U+000B inside the block makes the document invalid", block(with_(BASE, "\u000b")), invalid("C4"), ["C4"],
      disagreement=defect(4, "the compiler treats U+000B as a line break and the line as blank")),
    D("c5-blank-and-comment-lines", "Blank lines, blank-only lines and comment lines are skipped",
      block(["", ".dag: issue-dag/2", "   ", "# a comment", ".id: o/r#1", " \t# an indented comment", ".kind: task", "\t", ".type: feature", ".blocked_by: []"]),
      TASK, ["C5"]),
    D("c5-hash-inside-a-value", "A `#` inside a value is part of it", block(with_(BASE, "source: see o/r#12 # not a comment")), TASK, ["C5", "M3"]),
    D("c5-hash-after-a-format-value", "A `#` after a value does not start a comment", block(with_(BASE, ".type: feature # trailing", drop=(".type",))),
      invalid("V5"), ["C5", "V5"]),
    D("c5-nbsp-line", "A line holding U+00A0 is not blank: it is a line of another form", block(with_(BASE, " ")), invalid("C6"), ["C5", "C6"],
      disagreement=defect(5, "the compiler strips Unicode white space and skips the line")),
    D("c6-indented-entry", "An entry must start in the first column", block(with_(BASE, "  .size_hours: 2")), invalid("C6"), ["C6"]),
    D("c6-blanks-around-colon", "Blanks may surround the colon", block(with_(BASE, ".size_hours \t: \t2")), valid(rec(size=2)), ["C6", "L4"]),
    D("c6-trailing-blanks", "Trailing blanks are removed", block(with_(BASE, ".size_hours: 2 \t ")), valid(rec(size=2)), ["C6"]),
    D("c6-key-starts-with-digit", "A key must start with a letter or `_`", block(with_(BASE, "1st: x")), invalid("C6"), ["C6"]),
    D("c6-key-with-dash-and-digits", "A key may continue with letters, digits, `_` and `-`", block(with_(BASE, "_my-note2: x")), TASK, ["C6", "M3"]),
    D("c6-dot-alone-is-not-a-key", "A key of `.` alone is not a key", block(with_(BASE, ".: x")), invalid("C6"), ["C6"]),
    D("c6-no-colon", "A line without a colon is of another form", block(with_(BASE, "just text")), invalid("C6"), ["C6"]),
    D("c6-empty-value", "A value may be empty", block(with_(BASE, "note:")), TASK, ["C6", "C10"]),
    D("c6-block-list", "A YAML block list is lines of another form; the key's value is the empty string",
      block(with_(BASE, ".blocked_by:", "  - o/r#2", drop=(".blocked_by",))), invalid("C6", "V5"), ["C6", "C10", "V5"]),
    D("c6-nbsp-before-value", "U+00A0 before a value is part of the value", block(with_(BASE, ".type: feature", drop=(".type",))),
      invalid("V5"), ["C6", "V5"], disagreement=defect(5, "the compiler strips U+00A0 from the value and reads `feature`")),
    D("c7-duplicate-format-key", "A format key twice makes the document invalid", block(with_(BASE, ".type: bug")), invalid("C7"), ["C7"]),
    D("c7-duplicate-free-key", "A free key twice makes the document invalid", block(with_(BASE, "area: a", "area: b")), invalid("C7"), ["C7"]),
    D("c7-repeated-kind-task-then-container", "A repeated `.kind` is judged by C7 alone; another key's violation stays",
      block(with_(BASE, ".kind: container", ".status: done")), invalid("C7", "V8"), ["C7", "V5", "V6", "V8", "V12"]),
    D("c7-repeated-kind-container-then-task", "A repeated `.kind` in the other order gives the same labels",
      block([".dag: issue-dag/2", ".id: o/r#1", ".kind: container", ".type: feature", ".blocked_by: []", ".kind: task", ".status: done"]),
      invalid("C7", "V8"), ["C7", "V5", "V6", "V8", "V12"],
      disagreement=exception(20, "the compiler judges the first `.kind`, container, and reports V6 because the container has no `.children` (its truthiness check accepts the empty `.blocked_by`)")),
    D("c7-repeated-unknown-format-key", "A repeated format key outside M2 is labelled C7, not V2",
      block(with_(BASE, ".blockedby: [o/r#2]", ".blockedby: [o/r#3]")), invalid("C7"), ["C7", "V2", "V12"],
      disagreement=exception(20, "the compiler judges the first line and also reports V2")),
    D("c7-repeated-required-key-is-present", "A repeated `.blocked_by` is present: no V5 for its absence",
      block(with_(BASE, ".blocked_by: [o/r#2]")), invalid("C7"), ["C7", "V5", "V12"]),
    D("c7-repeated-type-values-not-judged", "The values of a repeated `.type` are not judged under V5",
      block(with_(BASE, ".type: chore", ".type: zzz", drop=(".type",))), invalid("C7"), ["C7", "V5", "V12"],
      disagreement=exception(20, "the compiler judges the first `.type` and also reports V5")),
    D("c7-repeated-children-on-a-task", "A repeated `.children` on a task is labelled C7, not V5",
      block(with_(BASE, ".children: []", ".children: [o/r#2]")), invalid("C7"), ["C7", "V5", "V12"],
      disagreement=exception(20, "the compiler judges the first `.children` and also reports V5")),
    D("c7-repeated-blocked-by-on-a-container", "A repeated `.blocked_by` on a container is labelled C7, not V6",
      block(with_(CONTAINER, ".blocked_by: []", ".blocked_by: [o/r#3]")), invalid("C7"), ["C7", "V6", "V12"]),
    D("c7-repeated-id", "A repeated `.id` leaves the identity unknown: no V7 and no X1",
      block(with_(BASE, ".id: o/r#2", ".blocked_by: [o/r#1]", drop=(".blocked_by",))), invalid("C7"), ["C7", "V3", "V7", "V12", "X1"],
      disagreement=exception(20, "the compiler judges the first `.id` and also reports V7")),
    D("c7-repeated-dag-with-another-violation", "A repeated `.dag` leaves the version unknown: C7 is the only violation",
      block(with_(BASE, ".dag: issue-dag/2", ".status: done")), invalid("C7"), ["C7", "V1", "V12"],
      disagreement=exception(21, "the compiler judges the document under the first `.dag` and also reports V8")),
    D("c7-repeated-dag-drops-line-violations", "A repeated `.dag` drops C6 and C8 on the other lines",
      block(with_(BASE, ".dag: issue-dag/2", "just text", "related: [a")), invalid("C7"), ["C7", "C6", "C8", "V12"],
      disagreement=exception(21, "the compiler also reports C6 and C8")),
    D("c7-repeated-dag-other-version-first", "A repeated `.dag` with another version first is C7 alone, not P3",
      block([".dag: issue-dag/3"] + BASE), invalid("C7"), ["C7", "P3", "V1", "V12"],
      disagreement=exception(21, "the compiler reads the first `.dag`, issue-dag/3, and also reports P3")),
    D("c7-repeated-dag-then-other-version", "A repeated `.dag` with the accepted version first is C7 alone",
      block(with_(BASE, ".dag: issue-dag/3")), invalid("C7"), ["C7", "P3", "V1", "V12"]),
    D("c7-repeated-dag-under-c4", "A body that fails C4 is not read into lines: a repeated `.dag` leaves C4 the only violation",
      block(with_(BASE, ".dag: issue-dag/2", "area: a\rb")), invalid("C4"), ["C4", "C7"],
      disagreement=defect(4, "the compiler splits the line at the CR and reports C6 and C7")),
    D("c8-repeated-unterminated-key-is-present", "A key repeated on two unterminated lines is present: C7 and C8, no V5",
      block(with_(BASE, ".blocked_by: [o/r#2", ".blocked_by: [o/r#3", drop=(".blocked_by",))), invalid("C7", "C8"), ["C7", "C8", "V5", "V12"],
      disagreement=exception(19, "the compiler counts neither unterminated line as an entry, so it reports V5 and no duplicate")),
    D("c8-unterminated-list", "A value that begins with `[` must end with `]`", block(with_(BASE, "related: [a, b")), invalid("C8"), ["C8"]),
    D("c8-unterminated-key-is-absent", "An unterminated list gives its key no value: a task without another `.blocked_by` lacks one",
      block(with_(BASE, ".blocked_by: [o/r#2", drop=(".blocked_by",))), invalid("C8", "V5"), ["C8", "V5", "V12"]),
    D("c8-unterminated-then-duplicate", "An unterminated list is still an entry line: a later line with its key is a duplicate",
      block(with_(BASE, ".size_hours: [3", ".size_hours: 3")), invalid("C7", "C8"), ["C7", "C8", "V12"],
      disagreement=exception(19, "the compiler does not count the unterminated line as an entry, so it reports no duplicate")),
    D("c8-duplicate-then-unterminated", "A duplicate line that also opens an unterminated list fails both C7 and C8",
      block(with_(BASE, ".size_hours: 3", ".size_hours: [3")), invalid("C7", "C8"), ["C7", "C8", "V12"],
      disagreement=exception(19, "the compiler stops at the duplicate key and does not judge the list")),
    D("c8-list-with-text-after", "Text after the closing bracket leaves the list unterminated", block(with_(BASE, "related: [a] b")), invalid("C8"), ["C8"]),
    D("c8-bracket-at-end-of-scalar", "A scalar may end with `]`", block(with_(BASE, "note: a]")), TASK, ["C8"]),
    D("c8-items-trimmed-and-unquoted", "List items are trimmed and unquoted",
      block(with_(BASE, ".holds: [ \"a\" , 'b' ,c ]")), valid(rec(holds=["a", "b", "c"])), ["C8", "C9", "L2"]),
    D("c8-empty-list-with-blanks", "A list of blanks is empty", block(with_(BASE, ".blocked_by: [  \t ]", drop=(".blocked_by",))), TASK, ["C8"]),
    D("c8-empty-item", "An empty item is the empty string, which is not a resource key", block(with_(BASE, ".holds: [a,,b]")), invalid("L2"), ["C8", "L2"]),
    D("c8-comma-in-quotes-splits", "A comma splits a list even inside quotes",
      block(with_(BASE, ".holds: [\"a,b\"]")), valid(rec(holds=["\"a", "b\""])), ["C8", "C9"]),
    D("c8-integer-with-leading-zeros", "An integer may have leading zeros", block(with_(BASE, ".size_hours: 007")), valid(rec(size=7)), ["C8", "L4"]),
    D("c8-list-items-are-strings", "A list item spelled as an integer stays a string",
      block(with_(BASE, ".holds: [007, -0]")), valid(rec(holds=["007", "-0"])), ["C8"],
      disagreement=defect(6, "the compiler converts the items to the integers 7 and 0 and back to `7` and `0`")),
    D("c8-negative-integer", "A negative integer is an integer, which `.size_hours` rejects", block(with_(BASE, ".size_hours: -3")), invalid("L4"), ["C8", "L4"]),
    D("c8-plus-sign-is-a-string", "A leading `+` makes a string", block(with_(BASE, ".size_hours: +2")), invalid("V8"), ["C8", "V8"]),
    D("c9-quoted-integer-is-a-string", "A quoted number is a string", block(with_(BASE, ".size_hours: \"2\"")), invalid("V8"), ["C8", "C9", "V8"]),
    D("c9-quoted-format-value", "A quoted format value is unquoted", block(with_(BASE, ".type: 'bug'", drop=(".type",))), valid(rec(type_="bug")), ["C9"]),
    D("c9-mismatched-quotes", "Mismatched quotes are part of the text", block(with_(BASE, ".type: \"bug'", drop=(".type",))), invalid("V5"), ["C9", "V5"]),
    D("c9-quote-inside", "A quote character may occur inside a quoted text", block(with_(BASE, ".holds: [\"a\"b\"]")), valid(rec(holds=["a\"b"])), ["C9"]),
    D("c9-single-quote-character", "A single quote character is its own text", block(with_(BASE, ".holds: [']")), valid(rec(holds=["'"])), ["C9"]),
    D("c9-quoted-empty-item", "A quoted empty item is the empty string", block(with_(BASE, ".holds: [\"\"]")), invalid("L2"), ["C9", "L2"]),
    D("c10-null-is-a-string", "`null` is a string", block(with_(BASE, ".status: null")), invalid("V8"), ["C10", "V8"]),
    D("c10-true-is-a-string", "`true` is a string", block(with_(BASE, ".status: true")), invalid("V8"), ["C10", "V8"]),
    D("c10-empty-is-not-a-list", "An empty value is a string, not an empty list", block(with_(BASE, ".blocked_by:", drop=(".blocked_by",))),
      invalid("V5"), ["C10", "V5"]),
    # Key binding: M1 to M4
    D("m3-free-keys-are-not-part-of-the-record", "Free keys are notes", block(with_(BASE, "area: x", "source: y", "related: [a, b]")), TASK, ["M1", "M3", "M4"]),
    D("m2-every-format-key", "A document with every format key",
      block(with_(BASE, ".size_hours: 3", ".holds: [docs/, src]", ".meters: [gpu*2]", ".status: active", drop=(".blocked_by",)) + [".blocked_by: [o/s#2, O/S#3]"]),
      valid(rec(blocked_by=["o/s#2", "o/s#3"], size=3, holds=["docs/", "src"], meters=[["gpu", 2]], status="active")), ["M2", "M4", "V5", "V8"]),
    D("m4-key-order-is-not-meaning", "Key order and spacing are not part of the record",
      block([".blocked_by:[o/r#2]", ".type:feature", ".kind :task", ".id: o/r#1", ".dag: issue-dag/2"]), valid(rec(blocked_by=["o/r#2"])), ["M4", "C6"]),
    # Values: L1 to L4
    D("l1-reference-canonical-form", "References are compared and recorded in lower case",
      block(with_(BASE, ".blocked_by: [My.Org/Re_po-X#12]", drop=(".blocked_by",))), valid(rec(blocked_by=["my.org/re_po-x#12"])), ["L1", "M4"]),
    D("l1-id-in-another-case", "An `.id` in another case names the same issue", block(with_(BASE, ".id: O/R#1", drop=(".id",))), TASK, ["L1", "X1"]),
    D("l1-bare-number", "A bare `#N` is not a reference", block(with_(BASE, ".blocked_by: [#2]", drop=(".blocked_by",))), invalid("L1"), ["L1"]),
    D("l1-number-alone", "A number alone is not a reference", block(with_(BASE, ".blocked_by: [2]", drop=(".blocked_by",))), invalid("L1"), ["L1"]),
    D("l1-leading-zero", "A reference number has no leading zero", block(with_(BASE, ".blocked_by: [o/r#02]", drop=(".blocked_by",))), invalid("L1"), ["L1"]),
    D("l1-number-zero", "A reference number is at least 1", block(with_(BASE, ".blocked_by: [o/r#0]", drop=(".blocked_by",))), invalid("L1"), ["L1"]),
    D("l1-url-is-not-a-reference", "A URL is not a reference",
      block(with_(BASE, ".blocked_by: [https://github.com/o/r/issues/2]", drop=(".blocked_by",))), invalid("L1"), ["L1"]),
    D("l1-space-inside", "A reference has no space inside", block(with_(BASE, ".blocked_by: [o/r #2]", drop=(".blocked_by",))), invalid("L1"), ["L1"]),
    D("l1-largest-number", "2147483647 is a reference number", block(with_(BASE, ".blocked_by: [o/r#2147483647]", drop=(".blocked_by",))),
      valid(rec(blocked_by=["o/r#2147483647"])), ["L1"]),
    D("l1-number-too-large", "A reference number above 2147483647 is invalid",
      block(with_(BASE, ".blocked_by: [o/r#2147483648]", drop=(".blocked_by",))), invalid("L1"), ["L1"],
      disagreement=defect(3, "the compiler's integers are unbounded")),
    D("l2-duplicate-resource-key", "A resource key may repeat; holds is a set", block(with_(BASE, ".holds: [a, b, a]")), valid(rec(holds=["a", "b"])), ["L2", "V9", "M4"]),
    D("l3-meter-claims", "A meter claim is a name with an optional slot count",
      block(with_(BASE, ".meters: [gpu, gpu*3, a.b/c-d_e]")), valid(rec(meters=[["gpu", 1], ["gpu", 3], ["a.b/c-d_e", 1]])), ["L3", "M4"]),
    D("l3-zero-slots", "A slot count is at least 1", block(with_(BASE, ".meters: [gpu*0]")), invalid("L3"), ["L3"]),
    D("l3-bad-name", "A meter name has no other characters", block(with_(BASE, ".meters: [gpu:2]")), invalid("L3"), ["L3"]),
    D("l3-slots-too-large", "A slot count above 2147483647 is invalid", block(with_(BASE, ".meters: [gpu*2147483648]")), invalid("L3"), ["L3"],
      disagreement=defect(3, "the compiler's integers are unbounded")),
    D("l4-size-zero", "`.size_hours` is at least 1", block(with_(BASE, ".size_hours: 0")), invalid("L4"), ["L4"]),
    D("l4-largest-size", "`.size_hours` may be 2147483647, with a warning", block(with_(BASE, ".size_hours: 2147483647")),
      valid(rec(size=2147483647), ("V10",)), ["L4", "V10"]),
    D("l4-size-too-large", "`.size_hours` above 2147483647 is invalid", block(with_(BASE, ".size_hours: 2147483648")), invalid("L4"), ["L4"],
      disagreement=defect(3, "the compiler's integers are unbounded; it accepts the value with a warning")),
    # Validity: V1 to V11, and X1 with the address
    D("v1-version-missing", "`.dag` must be present", block(BASE[1:]), invalid("V1"), ["V1"]),
    D("v1-version-quoted", "A quoted `.dag` is the same string", block(with_(BASE, ".dag: \"issue-dag/2\"", drop=(".dag",))), TASK, ["V1", "C9"]),
    D("v1-version-not-a-string", "An integer `.dag` is not the string issue-dag/2", block(with_(BASE, ".dag: 2", drop=(".dag",))), invalid("V1"), ["V1"]),
    D("v1-version-as-list", "A list `.dag` is invalid", block(with_(BASE, ".dag: [issue-dag/2]", drop=(".dag",))), invalid("V1"), ["V1"],
      disagreement=defect(7, "the validator raises TypeError and the run ends without an outcome")),
    D("p3-retired-version", "A retired version is rejected with its migration", block(with_(BASE, ".dag: issue-dag/1", drop=(".dag",))), invalid("P3"), ["P3", "V1"]),
    D("p3-unknown-version", "An unknown version is rejected", block(with_(BASE, ".dag: issue-dag/3", drop=(".dag",))), invalid("P3"), ["P3", "V1"]),
    D("v2-unknown-format-key", "A `.` key outside M2 is a violation", block(with_(BASE, ".blockedby: [o/r#2]")), invalid("V2"), ["V2", "M2"]),
    D("v3-id-missing", "`.id` must be present; a missing `.id` receives no X1 violation", block(with_(BASE, drop=(".id",))), invalid("V3"),
      ["V3", "V12", "X1"]),
    D("v3-id-not-a-string", "An integer `.id` is not a reference string", block(with_(BASE, ".id: 1", drop=(".id",))), invalid("V3"), ["V3", "V12", "X1"]),
    D("v3-bare-id", "A bare `.id` is a malformed reference, labelled L1; it receives no X1 violation",
      block(with_(BASE, ".id: #1", drop=(".id",))), invalid("L1"), ["V3", "L1", "V12", "X1"]),
    D("v1-version-empty", "An empty `.dag` is not a format name", block(with_(BASE, ".dag: \"\"", drop=(".dag",))), invalid("V1"), ["V1", "V12", "C9"]),
    D("v1-version-not-a-format-name", "A `.dag` that is not a format name is labelled V1", block(with_(BASE, ".dag: foo", drop=(".dag",))),
      invalid("V1"), ["V1", "V12", "P3"]),
    D("v4-kind-missing", "`.kind` must be present", block(with_(BASE, drop=(".kind",))), invalid("V4"), ["V4"]),
    D("v4-kind-other", "`.kind` is task or container", block(with_(BASE, ".kind: epic", drop=(".kind",))), invalid("V4"), ["V4"]),
    D("v4-kind-as-list", "A list `.kind` is invalid", block(with_(BASE, ".kind: [task]", drop=(".kind",))), invalid("V4"), ["V4"],
      disagreement=defect(7, "the validator raises TypeError and the run ends without an outcome")),
    D("v5-every-type", "Each `.type` of the enumeration is valid", block(with_(BASE, ".type: investigation", drop=(".type",))), valid(rec(type_="investigation")), ["V5"]),
    D("v5-type-missing", "A task needs `.type`", block(with_(BASE, drop=(".type",))), invalid("V5"), ["V5"]),
    D("v5-type-other", "`.type` outside the enumeration", block(with_(BASE, ".type: chore", drop=(".type",))), invalid("V5"), ["V5"]),
    D("v5-type-as-list", "A list `.type` is invalid", block(with_(BASE, ".type: [bug]", drop=(".type",))), invalid("V5"), ["V5"],
      disagreement=defect(7, "the validator raises TypeError and the run ends without an outcome")),
    D("v5-blocked-by-missing", "A task needs `.blocked_by`", block(with_(BASE, drop=(".blocked_by",))), invalid("V5"), ["V5"]),
    D("v5-blocked-by-scalar", "`.blocked_by` must be a list", block(with_(BASE, ".blocked_by: o/r#2", drop=(".blocked_by",))), invalid("V5"), ["V5"]),
    D("v5-task-with-children", "A task must not have `.children`", block(with_(BASE, ".children: []")), invalid("V5"), ["V5"]),
    D("v6-container", "A container with children", block(CONTAINER), CONTAINER_REC, ["V6", "M4"]),
    D("v6-container-no-children", "A container may have no children", block(with_(CONTAINER, ".children: []", drop=(".children",))),
      valid(rec(kind="container", type_=None, children=[])), ["V6"]),
    D("v6-container-children-missing", "A container needs `.children`", block(with_(CONTAINER, drop=(".children",))), invalid("V6"), ["V6"]),
    D("v6-container-children-scalar", "`.children` must be a list", block(with_(CONTAINER, ".children: o/r#2", drop=(".children",))), invalid("V6"), ["V6"]),
    D("v6-container-blocked-by", "A container must not have `.blocked_by`", block(with_(CONTAINER, ".blocked_by: [o/r#3]")), invalid("V6"), ["V6"]),
    D("v6-container-blocked-by-empty", "A container must not have `.blocked_by`, even `[]`", block(with_(CONTAINER, ".blocked_by: []")), invalid("V6"), ["V6"],
      disagreement=defect(1, "the compiler tests whether the value is falsy, not whether the key is present (decision 0001, 7)")),
    D("v6-container-blocked-by-zero", "A container must not have `.blocked_by`, even `0`", block(with_(CONTAINER, ".blocked_by: 0")), invalid("V6"), ["V6"],
      disagreement=defect(1, "the compiler tests whether the value is falsy, not whether the key is present")),
    D("v6-container-blocked-by-empty-value", "A container must not have `.blocked_by`, even empty", block(with_(CONTAINER, ".blocked_by:")), invalid("V6"), ["V6"],
      disagreement=defect(1, "the compiler tests whether the value is falsy, not whether the key is present")),
    D("v6-container-type", "A container may have a valid `.type`", block(with_(CONTAINER, ".type: research")),
      valid(rec(kind="container", type_="research", children=["o/r#2"])), ["V6"]),
    D("v6-container-type-other", "A container's `.type` must satisfy V5's value rule", block(with_(CONTAINER, ".type: zzz")), invalid("V6"), ["V6", "V5"],
      disagreement=defect(2, "the compiler does not check `.type` on a container")),
    D("v6-container-optional-keys", "`.size_hours`, `.holds`, `.meters` and `.status` are valid on a container",
      block(with_(CONTAINER, ".size_hours: 2", ".holds: [k]", ".meters: [m]", ".status: parked")),
      valid(rec(kind="container", type_=None, children=["o/r#2"], size=2, holds=["k"], meters=[["m", 1]], status="parked")), ["V6", "V8"]),
    D("v7-self-blocked-by", "A task may not name itself", block(with_(BASE, ".blocked_by: [o/r#1]", drop=(".blocked_by",))), invalid("V7"), ["V7"]),
    D("v7-self-in-another-case", "Self reference compares without case", block(with_(BASE, ".blocked_by: [O/R#1]", drop=(".blocked_by",))), invalid("V7"), ["V7", "L1"]),
    D("v7-self-child", "A container may not name itself", block(with_(CONTAINER, ".children: [o/r#1]", drop=(".children",))), invalid("V7"), ["V7"]),
    D("v7-names-its-id-not-its-address", "An item equal to `.id` is a self reference even when `.id` is not the address",
      block([".dag: issue-dag/2", ".id: o/r#2", ".kind: task", ".type: feature", ".blocked_by: [o/r#2]"]), invalid("V7", "X1"), ["V7", "X1"],
      disagreement=exception(8, "the compiler compares with the address; the document is invalid either way and the same issue receives the violations (F4)")),
    D("v7-names-its-address-not-its-id", "An item equal to the address but not to `.id` is not a self reference",
      block([".dag: issue-dag/2", ".id: o/r#2", ".kind: task", ".type: feature", ".blocked_by: [o/r#1]"]), invalid("X1"), ["V7", "X1"],
      disagreement=exception(8, "the compiler compares with the address; the document is invalid either way and the same issue receives the violations (F4)")),
    D("v8-status-values", "`.status` may be parked", block(with_(BASE, ".status: parked")), valid(rec(status="parked")), ["V8"]),
    D("v8-status-other", "`.status` outside its values", block(with_(BASE, ".status: done")), invalid("V8"), ["V8"]),
    D("v8-status-as-list", "A list `.status` is invalid", block(with_(BASE, ".status: [active]")), invalid("V8"), ["V8"],
      disagreement=defect(7, "the validator raises TypeError and the run ends without an outcome")),
    D("v8-holds-scalar", "`.holds` must be a list", block(with_(BASE, ".holds: docs")), invalid("V8"), ["V8"]),
    D("v8-meters-scalar", "`.meters` must be a list", block(with_(BASE, ".meters: gpu")), invalid("V8"), ["V8"]),
    D("v9-duplicate-prerequisites", "A reference may repeat; the record keeps it",
      block(with_(BASE, ".blocked_by: [o/r#2, o/r#2]", drop=(".blocked_by",))), valid(rec(blocked_by=["o/r#2", "o/r#2"])), ["V9", "M4"]),
    D("v10-size-above-eight", "A `.size_hours` above 8 is a warning only", block(with_(BASE, ".size_hours: 9")), valid(rec(size=9), ("V10",)), ["V10"]),
    D("v10-size-eight", "A `.size_hours` of 8 has no warning", block(with_(BASE, ".size_hours: 8")), valid(rec(size=8)), ["V10"]),
    D("v10-invalid-document-has-no-warnings", "An invalid document with a `.size_hours` above 8 has violations and no warnings",
      block(with_(BASE, ".size_hours: 12", ".status: done")), {**invalid("V8"), "warnings": []}, ["V10", "V8", "CC5"],
      disagreement=exception(22, "the compiler reports the V10 warning beside the violation")),
    D("v10-x1-document-has-no-warnings", "A document whose only violation is X1 has no warnings either",
      block(with_(BASE, ".id: o/r#2", ".size_hours: 12", drop=(".id",))), {**invalid("X1"), "warnings": []}, ["V10", "X1", "CC5"],
      disagreement=exception(22, "the compiler reports the V10 warning beside the X1 violation")),
    D("x1-id-is-not-the-address", "A copied document names another issue", block(with_(BASE, ".id: o/r#2", drop=(".id",))), invalid("X1"), ["X1", "V3"]),
]

# One body per shape of the census of 2026-11-12, in the census's order. All 282 documents were
# valid under the specification and the compiler alike.
_T = [".dag: issue-dag/2", ".id: o/r#1", ".kind: task", ".type: feature"]
_C = [".dag: issue-dag/2", ".id: o/r#1", ".kind: container"]
CENSUS_SHAPES: list[list[str]] = [
    _T + [".blocked_by: [o/r#2, o/s#3]", ".size_hours: 24", "area: planning"],
    _T + [".blocked_by: [o/r#2]"],
    _T + [".blocked_by: []"],
    _T + [".blocked_by: [o/r#2]", ".size_hours: 3"],
    _T + [".blocked_by: []", "area: docs", "source: o/r#7 and #8", "related: [o/r#9]"],
    _C + [".children: [o/r#2, o/s#3]", "area: roadmap"],
    _T + [".blocked_by: []", ".size_hours: 2", "area: tests"],
    _T + [".blocked_by: [o/r#2]", "area: core", "related: [o/r#5, o/r#6]"],
    _T + [".blocked_by: []", ".size_hours: 1"],
    _T + [".blocked_by: []", "area: cli", "related: [o/r#4]"],
    _T + [".blocked_by: []", "area: release", "source: o/r#3"],
    _T + [".blocked_by: []", "area: ci"],
    _T + [".blocked_by: [o/r#2]", ".holds: [docs/, src/parser]"],
    _T + [".blocked_by: [o/r#2]", "area: format"],
    _C + [".children: [o/r#2]"],
    _T + [".blocked_by: [o/r#2]", ".size_hours: 4", ".status: active"],
    _T + [".blocked_by: []", ".holds: [Cargo.lock]"],
]
CENSUS = [Doc(f"census-shape-{i:02d}", f"Census of 2026-11-12, shape {i}", block(lines, after="\n\n## Outcome\n\nFree text.\n"), None,
              source=f"evidence/2026-11-12-frontmatter-shapes.md, shape {i}") for i, lines in enumerate(CENSUS_SHAPES, start=1)]


# --------------------------------------------------------------------------- #
# Graphs
# --------------------------------------------------------------------------- #

R = "o/r"


def d(id_: str, blocked_by: tuple[str, ...] = (), kind: str = "task", children: list[str] | None = None, extra: str = "") -> str:
    return fm(id_, kind=kind, blocked_by=blocked_by, children=children, extra=extra)


def i(body: str, state: str = "open", reason: str | None = None, **kw: Any) -> dict[str, Any]:
    return issue(0, "", body, state=state, reason=reason, **kw)


def pr(number: int, closes: list[int], draft: Any = False, author: str | None = "dev", cross: bool | None = False, slug: str = R,
       bot: bool = False) -> dict[str, Any]:
    who: dict[str, Any] = {"login": author, "is_bot": True} if bot else {"login": author}
    out = {"number": number, "isDraft": draft, "url": "u", "author": who, "closingIssuesReferences": [closing(n, slug) for n in closes]}
    if cross is not None:
        out["isCrossRepository"] = cross
    return out


def bundle(issues: dict[str, dict[str, Any]], roots: tuple[str, ...] = (), prs: tuple[dict[str, Any], ...] = (), capacities: dict[str, int] | None = None,
           logins: tuple[str, ...] = ("dev",), owners: tuple[str, ...] = (), mutate: Callable[[dict[str, Any]], None] | None = None,
           codeowners: bool = False, codeowners_files: dict[str, dict[str, str]] | None = None, **state_extra: Any) -> dict[str, Any]:
    state = {"home": R, "default_author": "o", "blocked_by": {}, "issues": issues, "prs": list(prs), "codeowners": codeowners_files or {},
             **state_extra}
    b = ob.from_fake_state(state, roots=list(roots), trust={"owners": list(owners), "logins": list(logins), "codeowners": codeowners},
                           capacities=capacities)
    if mutate:
        mutate(b)
    return b


def unavailable(*path: str) -> Callable[[dict[str, Any]], None]:
    def go(b: dict[str, Any]) -> None:
        where = b["observations"]
        for key in path[:-1]:
            where = where[key]
        where[path[-1]] = {"unavailable": "recorded as unavailable for this case"}
    return go


def node(id_: str, status: str | None = "open", complete: bool = False, opaque: bool = False, untrusted: bool = False) -> dict[str, Any]:
    n: dict[str, Any] = {"id": id_, "complete": complete, "opaque": opaque, "untrusted": untrusted}
    if not complete:
        n["status"] = status
    return n


def done(id_: str, opaque: bool = False, untrusted: bool = False) -> dict[str, Any]:
    return node(id_, complete=True, opaque=opaque, untrusted=untrusted)


def e(a: str, b: str, status: str = "open") -> dict[str, str]:
    return {"from": a, "to": b, "status": status}


def f(subject: str, rule: str, concerns: str | None = None) -> dict[str, str]:
    out = {"subject": subject, "rule": rule}
    if concerns:
        out["concerns"] = concerns
    return out


def planned(nodes: list[dict[str, Any]], ready: list[str], batch: list[str], edges: list[dict[str, str]] = (), findings: list[dict[str, str]] = (),
            **more: Any) -> dict[str, Any]:
    out = {"outcome": "planned", "findings": sorted(findings, key=lambda x: (x["subject"], x["rule"], x.get("concerns", ""))),
           "nodes": sorted(nodes, key=lambda n: n["id"]), "edges": sorted(edges, key=lambda x: (x["from"], x["to"], x["status"])),
           "ready": ready, "batch": batch}
    out.update(more)
    return out


def invalid_run(*findings: dict[str, str]) -> dict[str, Any]:
    return {"outcome": "invalid", "findings": sorted(findings, key=lambda x: (x["subject"], x["rule"], x.get("concerns", "")))}


R1, R2, R3, R4, R5, R6, R9 = (f"{R}#{n}" for n in (1, 2, 3, 4, 5, 6, 9))
S2, S3 = "o/s#2", "o/s#3"
MALLORY = {"author": STRANGER, "association": "NONE"}
G = Graph
NORMATIVE_GRAPHS: list[Graph] = [
    # Inputs and outcome: I2, I5, F1, F2
    G("i2-root-outside-scope", "A root outside the read scope rejects the run", bundle({R1: i(d(R1))}, roots=("x/y#1",)), {"outcome": "rejected"}, ["I2", "F1"]),
    G("i2-root-not-a-reference", "A root that is not a reference rejects the run", bundle({R1: i(d(R1))}, roots=("#1",)), {"outcome": "rejected"}, ["I2", "F1"]),
    G("f1-rejected-before-incomplete", "A rejected run is rejected even when an observation is unavailable",
      bundle({R1: i(d(R1))}, roots=("x/y#1",), mutate=unavailable("home_open_pull_requests")), {"outcome": "rejected"}, ["F1", "I2", "I5"]),
    G("i5-pull-requests-unavailable", "An unavailable pull-request listing makes the run incomplete",
      bundle({R1: i(d(R1))}, roots=(R1,), mutate=unavailable("home_open_pull_requests")), {"outcome": "incomplete"}, ["I4", "I5", "F1", "F2"]),
    G("i5-home-listing-unavailable", "An unavailable listing of open home issues makes the run incomplete",
      bundle({R1: i(d(R1))}, mutate=unavailable("home_open_issues")), {"outcome": "incomplete"}, ["I4", "I5", "F2"]),
    G("i5-issue-unavailable", "An unavailable issue makes the run incomplete, not an empty answer",
      bundle({R1: i(d(R1, (R2,))), R2: i(d(R2))}, roots=(R1,), mutate=unavailable("issues", R2)), {"outcome": "incomplete"}, ["I3", "I5", "F2"]),
    G("d10-no-such-issue", "A reference that names no issue is an unavailable observation: the run is incomplete",
      bundle({R1: i(d(R1, (R2,)))}, roots=(R1,), mutate=lambda b: b["observations"]["issues"].update({R2: {"unavailable": "not found (HTTP 404)"}})),
      {"outcome": "incomplete"}, ["D10", "I5", "F1", "F2"]),
    G("i5-body-unavailable", "An unavailable body and edit history make the run incomplete",
      bundle({R1: i(d(R1, (R2,))), R2: i(d(R2))}, roots=(R1,), fail_graphql_for=[R2]), {"outcome": "incomplete"}, ["I3", "I5", "F2"]),
    G("i5-draft-flag-unavailable", "A draft flag that is not a boolean, on an admitted pull request, makes the run incomplete",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], draft="false"),)), {"outcome": "incomplete"}, ["I5", "S1", "S2"]),
    G("i5-draft-flag-of-an-unadmitted-pull-request", "The draft flag of a pull request that is not admitted is not read",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], draft="false", cross=True),)),
      planned([node(R1)], [R1], [R1], untrusted_pull_requests=[8]), ["I5", "S1", "W1", "AD9"]),
    G("i5-draft-flag-of-a-pull-request-closing-no-node", "The draft flag of an admitted pull request that closes no node is not read",
      bundle({R1: i(d(R1))}, roots=(R1,), prs=(pr(8, [5], draft="false"),)),
      planned([node(R1)], [R1], [R1], untrusted_pull_requests=[]), ["I4", "I5", "S1", "S2", "AD9"],
      disagreement=defect(23, "the compiler refuses the draft flag of every admitted pull request that closes an issue, and the run is incomplete")),
    G("i5-permission-unavailable", "A permission lookup that cannot be made makes the run incomplete",
      bundle({R1: i(d(R1), editors=["o", "carol"])}, roots=(R1,), collaborators_forbidden=True), {"outcome": "incomplete"}, ["I5", "F1", "AD8", "AD10"]),
    G("f1-incomplete-before-invalid", "An unavailable observation outranks a violation",
      bundle({R1: i(d(R1, (R2,), extra=".priority: 1")), R2: i(d(R2))}, roots=(R1,), mutate=unavailable("issues", R2)), {"outcome": "incomplete"}, ["F1"]),
    # Discovery: D1 to D9
    G("d1-seeds-are-the-open-home-issues", "Without roots, the seeds are the open issues of the home repository",
      bundle({R1: i(d(R1)), R2: i(d(R2), state="closed", reason="completed"), S3: i(d(S3))}),
      planned([node(R1)], [R1], [R1]), ["D1", "D2"]),
    G("d1-roots-are-the-seeds", "With roots, the seeds are the roots", bundle({R1: i(d(R1)), R2: i(d(R2))}, roots=(R2,)),
      planned([node(R2)], [R2], [R2]), ["D1"]),
    G("d2-closure-across-repositories", "The closure follows prerequisites across repositories",
      bundle({R1: i(d(R1, (S2,))), S2: i(d(S2, ("o/t#3",))), "o/t#3": i(d("o/t#3"), state="closed", reason="completed")}, roots=(R1,)),
      planned([node(R1), node(S2), done("o/t#3")], [S2], [S2], [e(S2, R1), e("o/t#3", S2, "satisfied")],
              scores={R1: 10, S2: 121}, waves=[[S2], [R1]], critical_path=[S2, R1]), ["D2", "D8", "G2", "G3", "K5", "K7", "K8"]),
    G("d2-references-compare-without-case", "Two spellings of one reference are one node and one edge",
      bundle({R1: i(d(R1, ("O/S#2", S2))), S2: i(d(S2))}, roots=(R1,)),
      planned([node(R1), node(S2)], [S2], [S2], [e(S2, R1)]), ["D2", "L1", "G3"]),
    G("d3-outside-the-scope", "A reference outside the read scope is never read; the document naming it receives a violation",
      bundle({R1: i(d(R1, ("x/y#1",)))}, roots=(R1,)), invalid_run(f(R1, "D3", "x/y#1"), f(R1, "X3", "x/y#1")), ["D3", "X3", "F1", "AD2"]),
    G("d3-each-document-naming-it", "Every document that names a reference outside the scope receives a violation, whatever the order of visits",
      bundle({R1: i(d(R1, ("x/y#1", R2))), R2: i(d(R2, ("x/y#1",)))}, roots=(R1,)),
      invalid_run(f(R1, "D3", "x/y#1"), f(R2, "D3", "x/y#1"), f(R1, "X3", "x/y#1"), f(R2, "X3", "x/y#1")), ["D2", "D3", "X3"],
      disagreement=defect(16, "the compiler gives the violation only to the documents visited before the reference")),
    G("d3-closed-document-naming-it", "A closed document that names a reference outside the scope receives a violation; no prerequisite is unknown",
      bundle({R1: i(d(R1, (R2,))), R2: i(d(R2, ("x/y#1",)), state="closed", reason="completed")}, roots=(R1,)),
      invalid_run(f(R2, "D3", "x/y#1")), ["D3", "D8", "X3"]),
    G("d4-pull-request", "A reference to a pull request receives a violation and is not a node",
      bundle({R1: i(d(R1, (R5,))), R5: i("", is_pr=True)}, roots=(R1,)), invalid_run(f(R5, "D4"), f(R1, "X3", R5)), ["D4", "X3"]),
    G("d5-transferred", "A transferred reference gives a violation to the document that names it",
      bundle({R1: i(d(R1, (R6,))), "o/s#66": i(d("o/s#66"))}, roots=(R1,), moved={R6: "o/s#66"}),
      invalid_run(f(R1, "D5", R6), f(R1, "X3", R6)), ["D5", "X3"]),
    G("d5-transferred-root", "A transferred root that no document names receives the violation itself",
      bundle({"o/s#66": i(d("o/s#66"))}, roots=(R6,), moved={R6: "o/s#66"}), invalid_run(f(R6, "D5", R6)), ["D5"]),
    G("d5-each-document-naming-it", "Every document that names a transferred reference receives a violation, whatever the order of visits",
      bundle({R1: i(d(R1, (R6, R2))), R2: i(d(R2, (R6,))), "o/s#66": i(d("o/s#66"))}, roots=(R1,), moved={R6: "o/s#66"}),
      invalid_run(f(R1, "D5", R6), f(R2, "D5", R6), f(R1, "X3", R6), f(R2, "X3", R6)), ["D2", "D5", "X3"],
      disagreement=defect(16, "the compiler gives the violation only to the documents visited before the reference")),
    G("d6-not-admitted-prerequisite", "An issue that is not admitted is an opaque, untrusted node whose body is not read",
      bundle({R1: i(d(R1, (R2,))), R2: i(d(R2, (R3,)), **MALLORY), R3: i(d(R3))}, roots=(R1,)),
      planned([node(R1), node(R2, "blocked", opaque=True, untrusted=True)], [R2], [], [e(R2, R1)], untrusted=[R2], scores={R1: 10, R2: 121}),
      ["D6", "T2", "S2", "Q2", "W1", "AD5", "AD8"]),
    G("d6-not-admitted-seed", "A seed that is not admitted and that no document names is only listed",
      bundle({R1: i(d(R1)), R3: i(d(R3), **MALLORY)}), planned([node(R1)], [R1], [R1], untrusted=[R3]), ["D6", "W1", "AD8"]),
    G("d6-not-admitted-root", "A root that is not admitted and that no document names is only listed",
      bundle({R3: i(d(R3), **MALLORY)}, roots=(R3,)), planned([], [], [], untrusted=[R3], critical_path=[]), ["D6", "K8", "AD8"]),
    G("d6-not-admitted-editor", "An issue with an editor who is not trusted is not admitted",
      bundle({R1: i(d(R1, (R2,))), R2: i(d(R2), editors=["o", STRANGER])}, roots=(R1,)),
      planned([node(R1), node(R2, "blocked", opaque=True, untrusted=True)], [R2], [], [e(R2, R1)], untrusted=[R2]), ["D6", "I3", "AD8"]),
    G("d7-no-frontmatter-is-opaque", "An admitted issue without frontmatter is an opaque node",
      bundle({R1: i(d(R1, (R2,))), R2: i("Plain body.")}, roots=(R1,)),
      planned([node(R1), node(R2, "blocked", opaque=True)], [R2], [], [e(R2, R1)]), ["D7", "S2", "Q1", "Q2"]),
    G("d7-unmodeled-seed", "A seed of a run without roots that has no frontmatter and that no document names is unmodeled",
      bundle({R1: i(d(R1)), R4: i("Plain body.")}), planned([node(R1)], [R1], [R1], unmodeled=[R4]), ["D7", "W1"]),
    G("d7-named-seed-is-opaque", "A seed without frontmatter that a document names is an opaque node",
      bundle({R1: i(d(R1, (R2,))), R2: i("Plain body.")}),
      planned([node(R1), node(R2, "blocked", opaque=True)], [R2], [], [e(R2, R1)], unmodeled=[]), ["D7", "X3"],
      disagreement=defect(9, "the compiler lists the issue as unmodeled and the prerequisite as unknown; the run is invalid")),
    G("d8-closed-document-is-validated", "A closed issue's document is validated",
      bundle({R1: i(d(R1, (R2,))), R2: i(d(R2, extra=".priority: 1"), state="closed", reason="completed")}, roots=(R1,)),
      invalid_run(f(R2, "V2")), ["D8", "V2"]),
    G("d8-invalid-document-is-walked", "Discovery follows the prerequisites of a document with violations",
      bundle({R1: i(d(R1, (R2,), extra=".priority: 1")), R2: i(d(R2, extra=".bogus: 2"))}, roots=(R1,)),
      invalid_run(f(R1, "V2"), f(R2, "V2")), ["D8"]),
    G("d8-own-address-is-not-followed", "A self reference is a violation and is not followed",
      bundle({R1: i(d(R1, (R1,)))}, roots=(R1,)), invalid_run(f(R1, "V7")), ["D8", "V7"]),
    G("d8-repeated-blocked-by-is-not-followed", "A repeated `.blocked_by` contributes no reference: an unavailable issue it names leaves the run invalid, not incomplete",
      bundle({R1: i(d(R1, (R2,), extra=".blocked_by: []"))}, roots=(R1,), mutate=lambda b: b["observations"]["issues"].update({R2: {"unavailable": "not found (HTTP 404)"}})),
      invalid_run(f(R1, "C7")), ["D8", "C7", "F1", "I5"],
      disagreement=defect(24, "the compiler reads the first `.blocked_by` line, follows the unavailable issue, and the run is incomplete")),
    G("d9-container", "A container is listed with its children and is not a node",
      bundle({R9: i(d(R9, kind="container", children=[R1, S2])), R1: i(d(R1)), S2: i(d(S2))}, roots=(R9,)),
      planned([node(R1), node(S2)], [R1, S2], [R1, S2], containers=[{"id": R9, "children": [R1, S2]}]), ["D9", "G1", "W1", "K6"]),
    G("d9-closed-container-is-walked", "Discovery walks a closed container's children",
      bundle({R9: i(d(R9, kind="container", children=[R1]), state="closed", reason="completed"), R1: i(d(R1))}, roots=(R9,)),
      planned([node(R1)], [R1], [R1], containers=[{"id": R9, "children": [R1]}]), ["D9"]),
    G("d9-invalid-container-is-walked", "Discovery walks an invalid container's children",
      bundle({R9: i(d(R9, kind="container", children=[R1], extra=".bogus: 1")), R1: i(d(R1, extra=".bogus: 2"))}, roots=(R9,)),
      invalid_run(f(R9, "V2"), f(R1, "V2")), ["D9", "D8"]),
    # Cross-document rules: X1 to X3
    G("x1-copied-document", "A document whose `.id` is not its issue's address receives a violation",
      bundle({R1: i(d(R2))}, roots=(R1,)), invalid_run(f(R1, "X1")), ["X1"]),
    G("x2-container-prerequisite", "An open task naming a container receives a violation and has no edge",
      bundle({R1: i(d(R1, (R9,))), R9: i(d(R9, kind="container", children=[]))}, roots=(R1,)), invalid_run(f(R1, "X2", R9)), ["X2", "X3"]),
    G("x2-closed-task-naming-a-container", "A closed task naming a container is not checked",
      bundle({R1: i(d(R1, (R9,)), state="closed", reason="completed"), R9: i(d(R9, kind="container", children=[]))}, roots=(R1,)),
      planned([done(R1)], [], [], containers=[{"id": R9, "children": []}], critical_path=[]), ["X2", "G3", "K8"]),
    # The graph: G1 to G5
    G("g2-not-planned-satisfies", "A prerequisite closed as not planned is complete; the pair is listed for review",
      bundle({R1: i(d(R1, (R2,))), R2: i(d(R2), state="closed", reason="not_planned")}, roots=(R1,)),
      planned([node(R1), done(R2)], [R1], [R1], [e(R2, R1, "satisfied")], not_planned=[{"from": R2, "to": R1}]), ["G2", "G3", "W1"]),
    G("g2-any-close-reason", "A prerequisite closed for any reason is complete",
      bundle({R1: i(d(R1, (R2,))), R2: i(d(R2), state="closed", reason="duplicate")}, roots=(R1,)),
      planned([node(R1), done(R2)], [R1], [R1], [e(R2, R1, "satisfied")], not_planned=[]), ["G2"]),
    G("g2-closed-opaque-is-complete", "A closed issue without frontmatter is a complete node",
      bundle({R1: i(d(R1, (R2,))), R2: i("Plain body.", state="closed", reason="completed")}, roots=(R1,)),
      planned([node(R1), done(R2, opaque=True)], [R1], [R1], [e(R2, R1, "satisfied")]), ["G2", "D7"]),
    G("g3-duplicate-prerequisite", "A prerequisite named twice is one edge",
      bundle({R1: i(d(R1, (R2, R2))), R2: i(d(R2))}, roots=(R1,)), planned([node(R1), node(R2)], [R2], [R2], [e(R2, R1)]), ["G3", "V9"]),
    G("g3-duplicate-not-planned-prerequisite", "A not-planned prerequisite named twice is one pair for review",
      bundle({R1: i(d(R1, (R2, R2))), R2: i(d(R2), state="closed", reason="not_planned")}, roots=(R1,)),
      planned([node(R1), done(R2)], [R1], [R1], [e(R2, R1, "satisfied")], not_planned=[{"from": R2, "to": R1}]), ["G3"],
      disagreement=exception(10, "the compiler lists one pair per occurrence; only the review list differs, never readiness, ranking or the batch")),
    G("g3-complete-node-has-no-edges", "A complete node's prerequisites are not evaluated",
      bundle({R1: i(d(R1, (R2,)), state="closed", reason="completed"), R2: i(d(R2))}, roots=(R1,)),
      planned([done(R1), node(R2)], [R2], [R2], []), ["G3"]),
    G("g4-cycle", "A cycle makes the run invalid; its members are reported",
      bundle({R1: i(d(R1, (R2,))), R2: i(d(R2, (R1,)))}, roots=(R1,)), invalid_run(f(R1, "G4"), f(R2, "G4")), ["G4"]),
    G("g4-downstream-of-a-cycle", "Nodes downstream of a cycle are reported; upstream ones are not",
      bundle({R3: i(d(R3, (R2,))), R2: i(d(R2, (R1,))), R1: i(d(R1, (R2, R4))), R4: i(d(R4))}, roots=(R3,)),
      invalid_run(f(R1, "G4"), f(R2, "G4"), f(R3, "G4")), ["G4"]),
    G("g5-redundant-edge", "An edge implied by a longer path is redundant",
      bundle({R3: i(d(R3, (R1, R2))), R2: i(d(R2, (R1,))), R1: i(d(R1))}, roots=(R3,)),
      planned([node(R1), node(R2), node(R3)], [R1], [R1], [e(R1, R2), e(R1, R3), e(R2, R3)], redundant=[{"from": R1, "to": R3}],
              scores={R1: 231, R2: 121, R3: 10}, waves=[[R1], [R2], [R3]], critical_path=[R1, R2, R3]),
      ["G5", "K1", "K2", "K3", "K5", "K7", "K8", "W1"]),
    # Status: S1, S2
    G("s2-draft-pull-request", "A task whose linked pull requests are all drafts is wip",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], draft=True),)), planned([node(R1, "wip")], [R1], [R1], scores={R1: 1010}), ["S1", "S2", "K4"]),
    G("s2-ready-pull-request", "A task with a linked pull request that is not a draft is in review",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], draft=True), pr(9, [1], draft=False))), planned([node(R1, "in-review")], [R1], [R1], scores={R1: 1010}),
      ["S1", "S2", "K4"]),
    G("s2-status-values", "`.status` gives in-progress, parked and blocked",
      bundle({R1: i(d(R1, extra=".status: active")), R2: i(d(R2, extra=".status: parked")), R3: i(d(R3, extra=".status: blocked")), R4: i(d(R4))}),
      planned([node(R1, "in-progress"), node(R2, "parked"), node(R3, "blocked"), node(R4)], [R1, R2, R3, R4], [R1, R2, R4],
              scores={R1: 1010, R2: 510, R3: 10, R4: 10}), ["S2", "K4", "K5", "K6", "Q2"]),
    G("s2-pull-request-overrides-blocked", "A linked pull request overrides `.status: blocked`",
      bundle({R1: i(d(R1, extra=".status: blocked"))}, prs=(pr(8, [1]),)), planned([node(R1, "in-review")], [R1], [R1]), ["S2", "Q2"]),
    G("s1-pull-request-not-admitted", "A pull request that is not admitted links nothing",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], cross=True),)), planned([node(R1)], [R1], [R1], untrusted_pull_requests=[8]), ["S1", "W1", "AD9"]),
    G("s1-node-outside-home", "A node outside the home repository has no linked pull request",
      bundle({R1: i(d(R1, (S2,))), S2: i(d(S2))}, roots=(R1,), prs=(pr(8, [2], slug="o/s"),)),
      planned([node(R1), node(S2)], [S2], [S2], [e(S2, R1)]), ["S1"]),
    G("s1-untrusted-node", "An untrusted node has no linked pull request",
      bundle({R1: i(d(R1, (R2,))), R2: i(d(R2), **MALLORY)}, prs=(pr(8, [2]),)),
      planned([node(R1), node(R2, "blocked", opaque=True, untrusted=True)], [R2], [], [e(R2, R1)], untrusted=[R2]), ["S1", "S2", "T2", "AD8"]),
    G("s2-opaque-with-pull-request", "An opaque node with a linked pull request is in review and still not dispatchable",
      bundle({R1: i(d(R1, (R2,))), R2: i("Plain body.")}, roots=(R1,), prs=(pr(8, [2]),)),
      planned([node(R1), node(R2, "in-review", opaque=True)], [R2], [], [e(R2, R1)], scores={R1: 10, R2: 1121}), ["S2", "Q2", "K4"]),
    # Ranking: K6
    G("k6-ties-compare-as-text", "Equal scores are ordered by identifier as text", bundle({"o/r#9": i(d("o/r#9")), "o/r#10": i(d("o/r#10"))}),
      planned([node("o/r#10"), node("o/r#9")], ["o/r#10", "o/r#9"], ["o/r#10", "o/r#9"]), ["K6"]),
    # Resources and batch: B1 to B5
    G("b1-keys-are-subtrees", "A key conflicts with the keys beneath it, not with a longer sibling",
      bundle({R1: i(d(R1, extra=".holds: [docs]")), R2: i(d(R2, extra=".holds: [docs/plans]")), R3: i(d(R3, extra=".holds: [docsx]"))}),
      planned([node(R1), node(R2), node(R3)], [R1, R2, R3], [R1, R3], skipped=[{"id": R2, "reason": "holds conflict"}]), ["B1", "B5"]),
    G("b1-trailing-slash", "`docs/` and `docs` conflict",
      bundle({R1: i(d(R1, extra=".holds: [docs/]")), R2: i(d(R2, extra=".holds: [docs]"))}),
      planned([node(R1), node(R2)], [R1, R2], [R1], skipped=[{"id": R2, "reason": "holds conflict"}]), ["B1"]),
    G("b2-one-key-space", "Equal keys in two repositories conflict",
      bundle({R9: i(d(R9, kind="container", children=[R1, S2])), R1: i(d(R1, extra=".holds: [lock]")), S2: i(d(S2, extra=".holds: [lock]"))}, roots=(R9,)),
      planned([node(R1), node(S2)], [R1, S2], [R1], skipped=[{"id": S2, "reason": "holds conflict"}]), ["B2", "B5"]),
    G("b3-unknown-capacity-is-one", "A semaphore without a capacity has capacity 1 and is reported",
      bundle({R1: i(d(R1, extra=".meters: [gpu]")), R2: i(d(R2, extra=".meters: [gpu]"))}),
      planned([node(R1), node(R2)], [R1, R2], [R1], skipped=[{"id": R2, "reason": "semaphore full", "semaphores": ["gpu"]}], unknown_capacity=["gpu"]),
      ["B3", "B4", "B5"]),
    G("b3-declared-capacity", "A declared capacity admits that many slots",
      bundle({R1: i(d(R1, extra=".meters: [gpu]")), R2: i(d(R2, extra=".meters: [gpu]"))}, capacities={"gpu": 2}),
      planned([node(R1), node(R2)], [R1, R2], [R1, R2], skipped=[], unknown_capacity=[]), ["B3"]),
    G("b3-only-names-that-are-considered", "A semaphore claimed only by a node that is not dispatchable is not reported",
      bundle({R1: i(d(R1, extra=".status: blocked\n.meters: [tpu]")), R2: i(d(R2, extra=".meters: [gpu]"))}),
      planned([node(R1, "blocked"), node(R2)], [R1, R2], [R2], unknown_capacity=["gpu"]), ["B3", "Q2"]),
    G("b3-names-in-byte-order", "Two unknown capacities and two full semaphores are named in ascending byte order",
      bundle({R1: i(d(R1, extra=".meters: [gpu, Tpu]")), R2: i(d(R2, extra=".meters: [gpu, Tpu]"))}),
      planned([node(R1), node(R2)], [R1, R2], [R1], skipped=[{"id": R2, "reason": "semaphore full", "semaphores": ["Tpu", "gpu"]}],
              unknown_capacity=["Tpu", "gpu"]), ["B3", "B5", "CC6"]),
    G("b4-need-is-the-sum", "A node's need is the sum of its claims",
      bundle({R1: i(d(R1, extra=".meters: [gpu*2, gpu]")), R2: i(d(R2, extra=".meters: [gpu]"))}, capacities={"gpu": 3}),
      planned([node(R1), node(R2)], [R1, R2], [R1], skipped=[{"id": R2, "reason": "semaphore full", "semaphores": ["gpu"]}]), ["B4", "B5", "L3"]),
    G("b5-holds-conflict-first", "A key conflict is the reason even when a semaphore is also full",
      bundle({R1: i(d(R1, extra=".holds: [a]\n.meters: [gpu]")), R2: i(d(R2, extra=".holds: [a]\n.meters: [gpu]"))}),
      planned([node(R1), node(R2)], [R1, R2], [R1], skipped=[{"id": R2, "reason": "holds conflict"}]), ["B5"]),
    # Reported lists: W1, with V10
    G("w1-warning", "A size above 8 is reported and does not invalidate the run",
      bundle({R1: i(d(R1, extra=".size_hours: 12"))}), planned([node(R1)], [R1], [R1], findings=[f(R1, "V10")]), ["W1", "V10"]),
]


# Admission (profiles/admission.md): AD1 to AD10. The subject is o/r#2 (or o/s#2), a prerequisite of the
# trusted root o/r#1: admitted, it is an open node; not admitted, an opaque, untrusted blocker (D6).
def subject(kw: dict[str, Any] | None = None, ref: str = R2, **opts: Any) -> dict[str, Any]:
    return bundle({R1: i(d(R1, (ref,))), ref: i(d(ref), **(kw or {}))}, roots=(R1,), **opts)


def admitted(ref: str = R2) -> dict[str, Any]:
    return planned([node(R1), node(ref)], [ref], [ref], [e(ref, R1)])


def refused(ref: str = R2) -> dict[str, Any]:
    return planned([node(R1), node(ref, "blocked", opaque=True, untrusted=True)], [ref], [], [e(ref, R1)], untrusted=[ref])


def set_issue(ref: str, **members: Any) -> Callable[[dict[str, Any]], None]:
    def go(b: dict[str, Any]) -> None:
        b["observations"]["issues"][ref]["value"].update(members)
    return go


def perms(repo: str, login: str) -> Callable[[dict[str, Any]], None]:
    return unavailable("permissions", repo, login)


INCOMPLETE = {"outcome": "incomplete"}
CAROL = "carol"
HELPER = {"author": "helper", "author_type": "Bot", "association": "NONE"}
OWNERS_FILE = ".github/CODEOWNERS"


def as_(association: str | None, author: str = CAROL) -> dict[str, Any]:
    return {"author": author, "association": association}


def writes(level: str, repo: str = R, login: str = CAROL) -> dict[str, Any]:
    return {"collaborators": {repo: {login: level}}}


def in_flight(**more: Any) -> dict[str, Any]:
    return planned([node(R1, "in-review")], [R1], [R1], scores={R1: 1010}, untrusted_pull_requests=[], **more)


def idle(*untrusted_prs: int) -> dict[str, Any]:
    return planned([node(R1)], [R1], [R1], scores={R1: 10}, untrusted_pull_requests=list(untrusted_prs))


NORMATIVE_GRAPHS += [
    # AD2: scope
    G("ad2-owner-in-another-scope-repository", "An author who is OWNER of another repository of the scope is trusted there",
      subject(as_("OWNER"), ref=S2), admitted(S2), ["AD2", "AD5", "AD8"]),
    G("ad2-permission-counts-per-repository", "Write permission on one repository does not trust the person in another",
      subject(as_("COLLABORATOR"), ref=S2, collaborators={R: {CAROL: "write"}, "o/s": {CAROL: "read"}}), refused(S2), ["AD2", "AD5", "AD6", "AD8", "D6"]),
    # AD3, AD4: identities and the allowlist
    G("ad3-allowlist-ignores-case", "An allowlisted login matches in any case",
      subject(as_("NONE", author="DEV"), logins=("Dev",)), admitted(), ["AD3", "AD4", "AD5"]),
    G("ad3-permission-ignores-case", "A permission is looked up under the login in lower case",
      subject(as_("MEMBER", author="Carol"), collaborators={R: {"Carol": "write"}}), admitted(), ["AD3", "AD6"]),
    G("ad3-editor-is-the-author-in-another-case", "An editor who is the author, spelled in another case, is not judged again",
      subject({"author": CAROL, "association": "OWNER", "editors": [CAROL, "CAROL"]}), admitted(), ["AD3", "AD8"]),
    G("ad3-bot-sharing-the-author-login", "A bot editor whose name is the author's login is another identity and is judged",
      subject({"author": "dev", "association": "NONE", "editors": ["dev", {"login": "dev", "type": "Bot"}]}), refused(), ["AD3", "AD4", "AD5", "AD8"]),
    G("ad3-bot-suffix-ignores-case", "A login ending in `[BOT]` is the bot it names, trusted by a `[bot]` entry",
      subject(as_("NONE", author="Helper[BOT]"), logins=("helper[bot]",)), admitted(), ["AD3", "AD4", "AD5"]),
    G("ad3-app-prefix-ignores-case", "A login beginning with `App/` is the bot it names, trusted by an `app/` entry",
      subject(as_("NONE", author="App/helper"), logins=("app/helper",)), admitted(), ["AD3", "AD4", "AD5"]),
    G("ad3-app-prefix-in-any-case-is-a-bot", "A login beginning with `APP/` is a bot: its OWNER association does not trust it",
      subject(as_("OWNER", author="APP/helper")), refused(), ["AD3", "AD5"]),
    G("ad4-entry-suffix-ignores-case", "Allowlisting `HELPER[Bot]` trusts the app `helper`",
      subject(HELPER, logins=("HELPER[Bot]",)), admitted(), ["AD3", "AD4", "AD5"]),
    G("ad4-entry-prefix-ignores-case", "Allowlisting `APP/helper` trusts the app `helper`",
      subject(HELPER, logins=("APP/helper",)), admitted(), ["AD3", "AD4", "AD5"]),
    G("ad4-person-entry-does-not-trust-the-bot", "Allowlisting `helper` does not trust the app `helper`",
      subject(HELPER, logins=("helper",)), refused(), ["AD4", "AD5"]),
    G("ad4-bot-entry-trusts-the-bot", "Allowlisting `helper[bot]` trusts the app `helper`",
      subject(HELPER, logins=("helper[bot]",)), admitted(), ["AD3", "AD4", "AD5"]),
    G("ad4-app-entry-trusts-the-bot", "Allowlisting `app/helper` trusts the app `helper`",
      subject(HELPER, logins=("app/helper",)), admitted(), ["AD3", "AD4", "AD5"]),
    G("ad4-bot-entry-does-not-trust-the-person", "Allowlisting `helper[bot]` does not trust the person `helper`",
      subject(as_("NONE", author="helper"), logins=("helper[bot]",)), refused(), ["AD3", "AD4", "AD5"]),
    # AD5: judging one actor
    G("ad5-deleted-author", "A deleted author is not trusted", subject(mutate=set_issue(R2, author=None)), refused(), ["AD5", "AD8"]),
    G("ad5-deleted-editor", "A deleted editor is not trusted", subject({"editors": ["o", None]}), refused(), ["AD5", "AD8"]),
    G("ad5-bot-not-allowlisted", "A bot that is not allowlisted is not trusted", subject(HELPER), refused(), ["AD5"]),
    G("ad5-owner-association", "An author whose association is OWNER is trusted without a permission", subject(as_("OWNER")), admitted(), ["AD5"]),
    G("ad5-member-with-write", "A MEMBER with write permission is trusted", subject(as_("MEMBER"), **writes("write")), admitted(), ["AD5", "AD6"]),
    G("ad5-member-with-read", "A MEMBER with read permission is not trusted", subject(as_("MEMBER"), **writes("read")), refused(), ["AD5", "AD6", "D6"]),
    G("ad5-collaborator-with-maintain", "A COLLABORATOR with maintain permission is trusted",
      subject(as_("COLLABORATOR"), **writes("maintain")), admitted(), ["AD5", "AD6"]),
    G("ad5-collaborator-with-admin", "A COLLABORATOR with admin permission is trusted",
      subject(as_("COLLABORATOR"), **writes("admin")), admitted(), ["AD5", "AD6"]),
    G("ad5-collaborator-with-triage", "A COLLABORATOR with triage permission is not trusted",
      subject(as_("COLLABORATOR"), **writes("triage")), refused(), ["AD5", "AD6", "D6"]),
    G("ad5-collaborator-not-a-collaborator", "A COLLABORATOR association with no permission is not trusted",
      subject(as_("COLLABORATOR")), refused(), ["AD5", "AD6"]),
    G("ad5-other-association-decides", "An association outside OWNER, MEMBER and COLLABORATOR decides without the permission",
      subject(as_("CONTRIBUTOR"), **writes("write")), refused(), ["AD5", "AD10"]),
    G("ad5-no-association-reads-the-permission", "An author with no recorded association is judged by the permission",
      subject(as_("NONE"), mutate=set_issue(R2, author_association=None), **writes("write")), admitted(), ["AD5", "AD6"]),
    # AD7: CODEOWNERS
    G("ad7-codeowners-person", "A person named in CODEOWNERS is trusted in that repository",
      subject(as_("NONE"), codeowners=True, codeowners_files={R: {OWNERS_FILE: "* @o @Carol\n"}}), admitted(), ["AD7", "AD5", "AD3"]),
    G("ad7-codeowners-later-path", "CODEOWNERS is read from the first of its paths that exists",
      subject(as_("NONE"), codeowners=True, codeowners_files={R: {"docs/CODEOWNERS": "/src/ @carol\n"}}), admitted(), ["AD7"]),
    G("ad7-codeowners-team-is-not-expanded", "A team named in CODEOWNERS trusts nobody",
      subject(as_("MEMBER"), codeowners=True, codeowners_files={R: {OWNERS_FILE: "* @o/core\n"}}, **writes("read")), refused(), ["AD7", "AD5"]),
    G("ad7-codeowners-comment", "A name after `#` in CODEOWNERS is a comment",
      subject(as_("NONE"), codeowners=True, codeowners_files={R: {OWNERS_FILE: "* @o # @carol\n"}}), refused(), ["AD7"]),
    G("ad7-codeowners-of-another-repository", "CODEOWNERS of one repository trusts nobody in another",
      subject(as_("NONE"), ref=S2, codeowners=True, codeowners_files={R: {OWNERS_FILE: "* @o @carol\n"}}), refused(S2), ["AD7", "AD2"]),
    G("ad7-codeowners-does-not-trust-a-bot", "A bot named in CODEOWNERS is not trusted",
      subject(HELPER, codeowners=True, codeowners_files={R: {OWNERS_FILE: "* @helper[bot]\n"}}), refused(), ["AD7", "AD5"]),
    G("ad7-codeowners-off", "CODEOWNERS is not read when the policy does not read it",
      subject(as_("NONE")), refused(), ["AD7", "AD1"]),
    # AD8: issue admission
    G("ad8-trusted-editors", "An issue whose author and every editor are trusted is admitted",
      subject({"editors": ["o", CAROL]}, **writes("write")), admitted(), ["AD8"]),
    G("ad8-untrusted-editor-after-trusted-author", "One untrusted editor after a trusted author refuses the issue",
      subject({"editors": ["o", CAROL, STRANGER]}, **writes("write")), refused(), ["AD8", "D6"]),
    G("ad8-every-editor-is-judged", "An unavailable lookup of a later editor makes the run incomplete, even after an untrusted one",
      subject({"editors": ["o", STRANGER, CAROL]}, mutate=perms(R, CAROL)), INCOMPLETE, ["AD8", "AD10", "I5"]),
    G("ad8-body-of-an-untrusted-author-is-not-read", "The body of an issue whose author is not trusted is not read",
      subject(MALLORY, fail_graphql_for=[R2]), refused(), ["AD8", "AD10", "D6"]),
    # AD9: pull requests
    G("ad9-same-repository-trusted-author", "A same-repository pull request by an author with write permission is admitted",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], author=CAROL),), **writes("write")), in_flight(), ["AD9", "S1", "S2"]),
    G("ad9-same-repository-untrusted-author", "A same-repository pull request by an author without write permission is not admitted",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], author=CAROL),), **writes("triage")), idle(8), ["AD9", "S1", "W1"]),
    G("ad9-fork-by-a-trusted-author", "A pull request from a fork is not admitted, whoever opened it",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], cross=True),)), idle(8), ["AD9", "S1"]),
    G("ad9-head-not-observed", "A pull request whose head repository was not observed is not admitted",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], cross=None),)), idle(8), ["AD9"]),
    G("ad9-deleted-author", "A pull request by a deleted account is not admitted",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], author=None),)), idle(8), ["AD9", "AD5"]),
    G("ad9-bot-author", "A pull request by a bot that is not allowlisted is not admitted",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], author="app/helper", bot=True),)), idle(8), ["AD9", "AD5"]),
    G("ad9-allowlisted-bot-author", "A pull request by an allowlisted bot is admitted",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], author="app/helper", bot=True),), logins=("helper[bot]",)), in_flight(), ["AD9", "AD4"]),
    G("ad9-permission-unavailable", "An unavailable permission of a pull request's author makes the run incomplete",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], author=CAROL),), mutate=perms(R, CAROL)), INCOMPLETE, ["AD9", "AD10"]),
    G("ad9-fork-author-is-not-judged", "The author of a pull request from a fork is not judged, so its permission is not required",
      bundle({R1: i(d(R1))}, prs=(pr(8, [1], author=CAROL, cross=True),), mutate=perms(R, CAROL)), idle(8), ["AD9", "AD10"]),
    G("ad9-closing-nothing-is-not-judged", "A pull request that closes no issue reads nothing",
      bundle({R1: i(d(R1))}, prs=(pr(8, [], author=CAROL),), mutate=perms(R, CAROL)), idle(), ["AD9", "AD10"]),
    # AD10: completeness
    G("ad10-codeowners-unavailable", "An unavailable CODEOWNERS that a judgement reads makes the run incomplete",
      subject(as_("NONE"), codeowners=True, contents_fail=True), INCOMPLETE, ["AD7", "AD10", "I5"]),
    G("ad10-codeowners-not-reached", "An unavailable CODEOWNERS that no judgement reaches is not required",
      subject(as_("NONE"), codeowners=True, contents_fail=True, logins=("o", CAROL)), admitted(), ["AD5", "AD10"]),
    G("ad10-permission-not-reached", "The permission of an author whose association decides is not required",
      subject(MALLORY, collaborators_forbidden=True), refused(), ["AD5", "AD10"]),
    G("ad10-owner-permission-not-reached", "The permission of an author trusted as OWNER is not required",
      subject(as_("OWNER"), collaborators_forbidden=True), admitted(), ["AD5", "AD10"]),
    G("ad10-allowlisted-permission-not-reached", "The permission of an allowlisted login is not required",
      subject(as_("MEMBER"), logins=("dev", CAROL), collaborators_forbidden=True), admitted(), ["AD4", "AD5", "AD10"]),
    G("ad10-bot-lookups-not-reached", "Neither the permission nor the CODEOWNERS a bot would need is required",
      subject(HELPER, logins=("o",), codeowners=True, contents_fail=True, mutate=perms(R, "helper")), refused(), ["AD5", "AD10"]),
    # AD7: how CODEOWNERS is read
    G("ad7-codeowners-nbsp-separates", "U+00A0 separates CODEOWNERS owners",
      subject(as_("NONE"), codeowners=True, codeowners_files={R: {OWNERS_FILE: "* @o @carol\n"}}), admitted(), ["AD7"]),
    G("ad7-codeowners-line-separator-ends-a-line", "U+2028 ends a CODEOWNERS line: `@carol` after it is the next line's pattern, not an owner",
      subject(as_("NONE"), codeowners=True, codeowners_files={R: {OWNERS_FILE: "* @o @carol\n"}}), refused(), ["AD7"]),
    G("ad7-codeowners-bare-at", "A bare `@` in CODEOWNERS names nobody",
      subject(as_("NONE"), codeowners=True, codeowners_files={R: {OWNERS_FILE: "* @o @\n"}}), refused(), ["AD7"]),
    G("ad7-codeowners-email", "An e-mail address in CODEOWNERS names nobody",
      subject(as_("NONE"), codeowners=True, codeowners_files={R: {OWNERS_FILE: "* @o carol@example.com\n"}}), refused(), ["AD7"]),
    G("ad7-codeowners-trusts-an-editor", "An editor named in CODEOWNERS is trusted without a permission",
      subject({"editors": ["o", CAROL]}, codeowners=True, codeowners_files={R: {OWNERS_FILE: "* @o @carol\n"}}), admitted(), ["AD7", "AD8"]),
]

NORMATIVE_GRAPHS.append(
    G("i2-other-trust-policy", "A run under a trust policy that the specification does not define is rejected",
      bundle({R1: i(d(R1))}, roots=(R1,), mutate=lambda b: b["parameters"]["trust"].update(policy="someone/else")),
      {"outcome": "rejected"}, ["I2", "I6", "F1"]))


# Which lookup a run reports when several could not be made: bundle rule OB16 (flyingrobots/taskalisk#117).
# Each case comes in both orders of its roots, and the slot reported is never the first root's, in one
# of them, so a planner that stops at the first lookup it cannot make fails one of the pair.
R10 = f"{R}#10"


def slots(changes: dict[str, str | None], codeowners_of: str | None = None) -> Callable[[dict[str, Any]], None]:
    """For each reference: None leaves its issue slot out of the bundle (OB5); any other text records
    the issue as unavailable with that reason (OB4). `codeowners_of` leaves out that repository's
    CODEOWNERS slot."""
    def go(b: dict[str, Any]) -> None:
        issues = b["observations"]["issues"]
        for ref, change in changes.items():
            if change is None:
                del issues[ref]
            else:
                issues[ref] = {"unavailable": change}
        if codeowners_of is not None:
            del b["observations"]["codeowners"][codeowners_of]
    return go


def no_body(ref: str) -> Callable[[dict[str, Any]], None]:
    """Leaves out the body of `ref` (OB8, OB14), which the run reads."""
    def go(b: dict[str, Any]) -> None:
        del b["observations"]["issues"][ref]["value"]["body"]
    return go


def no_permission(repo: str, login: str) -> Callable[[dict[str, Any]], None]:
    def go(b: dict[str, Any]) -> None:
        b["observations"]["permissions"].get(repo, {}).pop(login, None)
    return go


def drafts(reasons: dict[int, str]) -> Callable[[dict[str, Any]], None]:
    """Records the draft flag of each pull request numbered in `reasons` as unavailable, with that reason (OB7)."""
    def go(b: dict[str, Any]) -> None:
        for item in b["observations"]["home_open_pull_requests"]["value"]:
            if item["number"] in reasons:
                item["draft"] = {"unavailable": reasons[item["number"]]}
    return go


def steps(*fns: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
    def go(b: dict[str, Any]) -> None:
        for fn in fns:
            fn(b)
    return go


def both_orders(name: str, title: str, first: str, second: str, mutate: Callable[[dict[str, Any]], None],
                expected: dict[str, Any], cites: list[str], disagreement: dict[str, Any] | None,
                issues: dict[str, dict[str, Any]] | None = None, **opts: Any) -> list[Graph]:
    issues = issues or {first: i(d(first)), second: i(d(second))}
    return [G(f"{name}{suffix}", f"{title}{note}", bundle(issues, roots=roots, mutate=mutate, **opts), expected, cites, disagreement=disagreement)
            for suffix, note, roots in (("", "", (first, second)), ("-roots-reversed", ", with the roots in the other order", (second, first)))]


# Two open home tasks, each closed by an admitted pull request (S1): #10 closes o/r#2, #11 closes o/r#3.
LINKED = (pr(10, [2]), pr(11, [3]))
STOPS = "the compiler stops at the first lookup it cannot make"
NO_REASON = "the compiler reports an incomplete run without the reason recorded in any slot"
NORMATIVE_GRAPHS += [
    *both_orders("ob16-missing-over-unavailable", "A missing slot is reported, not an unavailable one", R2, R3,
                 slots({R2: "HTTP 502", R3: None}), {"outcome": "unusable", "missing": ["issues", R3]}, ["OB16", "OB5", "F1"],
                 exception(25, f"{STOPS}: it reads the unavailable o/r#2 first and reports an incomplete run")),
    *both_orders("ob16-least-of-two-missing", "Of two missing slots, the least is reported: `o/r#10` before `o/r#2`", R2, R10,
                 slots({R2: None, R10: None}), {"outcome": "unusable", "missing": ["issues", R10]}, ["OB16", "OB5"],
                 exception(25, f"{STOPS}: it reads o/r#2 first and reports it")),
    *both_orders("ob16-missing-codeowners-before-missing-issue", "A missing CODEOWNERS comes before a missing issue", R2, R3,
                 slots({R2: None}, codeowners_of=R), {"outcome": "unusable", "missing": ["codeowners", R]}, ["OB16", "OB5", "AD10"],
                 exception(25, f"{STOPS}: it reads the issue o/r#2 first and reports it"), codeowners=True),
    *both_orders("ob16-least-of-two-unavailable", "Of two unavailable slots, the least reason is reported", R2, R3,
                 slots({R2: "timeout", R3: "HTTP 502"}), {"outcome": "incomplete", "unavailable": "HTTP 502"}, ["OB16", "F1", "I5"],
                 exception(26, NO_REASON)),
    # The draft flags S2 reads: the least reason, whichever node holds it.
    *both_orders("ob16-least-draft-flag-on-the-last-node", "Of two unavailable draft flags, the least reason is reported, on the later node",
                 R2, R3, drafts({10: "timeout", 11: "HTTP 502"}), {"outcome": "incomplete", "unavailable": "HTTP 502"},
                 ["OB16", "S2", "I5"], exception(26, NO_REASON), prs=LINKED),
    *both_orders("ob16-least-draft-flag-on-the-first-node", "Of two unavailable draft flags, the least reason is reported, on the earlier node",
                 R2, R3, drafts({10: "HTTP 502", 11: "timeout"}), {"outcome": "incomplete", "unavailable": "HTTP 502"},
                 ["OB16", "S2", "I5"], exception(26, NO_REASON), prs=LINKED),
    *both_orders("ob16-unavailable-issue-before-draft-flag", "An unavailable issue is reported, not a draft flag with a lesser reason: "
                 "S2 is not reached", R2, R3, steps(slots({R2: "timeout"}), drafts({11: "HTTP 502"})),
                 {"outcome": "incomplete", "unavailable": "timeout"}, ["OB16", "S2", "F2"], exception(26, NO_REASON), prs=LINKED),
    # Missing slots by path (OB16): kinds that the order of the bundle's member names decides.
    *both_orders("ob16-missing-issue-before-a-later-body", "The missing issue o/r#2 comes before the missing body of o/r#3", R2, R3,
                 steps(slots({R2: None}), no_body(R3)), {"outcome": "unusable", "missing": ["issues", R2]}, ["OB16", "OB5"], None),
    *both_orders("ob16-least-of-two-permissions", "Of two missing permissions, the one on o/r comes first, whatever the logins",
                 R2, S3, steps(no_permission(R, "dave"), no_permission("o/s", CAROL)),
                 {"outcome": "unusable", "missing": ["permissions", R, "dave"]}, ["OB16", "OB5", "AD5"], None,
                 issues={R2: i(d(R2), **as_("COLLABORATOR", "dave")), S3: i(d(S3), **as_("COLLABORATOR"))}),
]


# --------------------------------------------------------------------------- #
# Scenarios from the compiler's tests
# --------------------------------------------------------------------------- #


def _state(build: Callable[[dict[str, Any]], None] | None = None, base: Callable[[], dict[str, Any]] = plan_state) -> dict[str, Any]:
    state = copy.deepcopy(base())
    if build:
        build(state)
    return state


def _body(ref: str, body: str) -> Callable[[dict[str, Any]], None]:
    def go(s: dict[str, Any]) -> None:
        s["issues"][ref]["body"] = body
    return go


def _add(ref: str, value: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
    def go(s: dict[str, Any]) -> None:
        s["issues"][ref] = value
    return go


def _all(*steps: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
    def go(s: dict[str, Any]) -> None:
        for step in steps:
            step(s)
    return go


def _set(**kw: Any) -> Callable[[dict[str, Any]], None]:
    def go(s: dict[str, Any]) -> None:
        s.update(copy.deepcopy(kw))
    return go


def _edit(ref: str, **kw: Any) -> Callable[[dict[str, Any]], None]:
    def go(s: dict[str, Any]) -> None:
        s["issues"][ref].update(copy.deepcopy(kw))
    return go


def _moved(s: dict[str, Any]) -> None:
    s["moved"] = {f"{ECHO}#6": f"{BUNNY}#66"}
    s["issues"][f"{BUNNY}#66"] = s["issues"].pop(f"{ECHO}#6")


def _mis_cased(s: dict[str, Any]) -> None:
    s["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=["FlyingRobots/Echo#5"])
    s["issues"]["FlyingRobots/Echo#5"] = s["issues"].pop(f"{ECHO}#5")


def _frontier(extra_a: str, extra_b: str) -> Callable[[], dict[str, Any]]:
    return lambda: {"home": HOME, "blocked_by": {}, "issues": {f"{HOME}#1": issue(101, "A", fm(f"{HOME}#1", extra=extra_a)),
                                                                f"{HOME}#2": issue(102, "B", fm(f"{HOME}#2", extra=extra_b))}}


def _with_prs(drafts: list[Any], extra: str = "") -> Callable[[], dict[str, Any]]:
    def build() -> dict[str, Any]:
        prs = [{"number": 10 + n, "isDraft": draft, "url": "u", "author": {"login": "owner"}, "isCrossRepository": False,
                "closingIssuesReferences": [closing(1)]} for n, draft in enumerate(drafts)]
        return {"home": HOME, "blocked_by": {}, "collaborators": {HOME: ["owner"]}, "prs": prs,
                "issues": {f"{HOME}#1": issue(101, "Work", fm(f"{HOME}#1", extra=extra))}}
    return build


def _cycle(s: dict[str, Any]) -> None:
    s["issues"][f"{ECHO}#5"]["body"] = fm(f"{ECHO}#5", blocked_by=[f"{HOME}#2"])


def _stranger_dependents(s: dict[str, Any]) -> None:
    for n in range(50, 53):
        s["issues"][f"{HOME}#{n}"] = issue(1000 + n, "Fake dependent", fm(f"{HOME}#{n}", blocked_by=[f"{HOME}#2"]), author=STRANGER, association="NONE")


ROOT9 = (f"{HOME}#9",)
T = "tests/test_taskalisk.py"
# name: (source, state, roots, trust, capacities)
SCENARIO_TABLE: list[tuple[str, str, dict[str, Any], tuple[str, ...], dict[str, Any] | None, dict[str, int] | None]] = [
    ("golden-plan-root", "tests/golden_scenarios.py plan_root", _state(), ROOT9, None, None),
    ("golden-plan-home", "tests/golden_scenarios.py plan_home", _state(), (), None, None),
    ("golden-plan-rich", "tests/golden_scenarios.py plan_rich", _state(base=golden.rich_state), (), None, {"gpu": 1}),
    ("golden-roadmap-root", "tests/golden_scenarios.py roadmap_root", _state(base=golden.rich_state), (), None, None),
    ("golden-plan-violations", "tests/golden_scenarios.py plan_violations", _state(base=golden.violation_state), ROOT9, None, None),
    ("golden-plan-gh-failure", "tests/golden_scenarios.py plan_gh_failure", _state(base=golden.gh_failure_state), (), None, None),
    ("discovery-unmodeled-home-issue", f"{T} Discovery.test_home_issue_without_frontmatter_is_listed_not_a_node",
     _state(_add(f"{HOME}#40", issue(140, "Legacy", "No frontmatter here."))), (), None, None),
    ("validation-unknown-key", f"{T} Validation.test_unknown_dot_key_fails", _state(_body(f"{HOME}#1", fm(f"{HOME}#1", extra=f".blockedby: [{HOME}#2]"))), ROOT9, None, None),
    ("validation-copied-id", f"{T} Validation.test_copied_frontmatter_with_wrong_id_fails", _state(_body(f"{HOME}#1", fm(f"{HOME}#2", blocked_by=[f"{ECHO}#5"]))), ROOT9, None, None),
    ("validation-no-blocked-by", f"{T} Validation.test_task_without_blocked_by_fails",
     _state(_body(f"{HOME}#1", f"```yaml\n.dag: issue-dag/2\n.id: {HOME}#1\n.kind: task\n.type: feature\n```\n")), ROOT9, None, None),
    ("validation-container-as-blocker", f"{T} Validation.test_container_as_blocker_fails", _state(_body(f"{HOME}#1", fm(f"{HOME}#1", blocked_by=[f"{HOME}#9"]))), ROOT9, None, None),
    ("validation-unparseable-line", f"{T} Validation.test_unparseable_line_fails", _state(_body(f"{HOME}#1", fm(f"{HOME}#1", extra="  nested:\n    - x"))), ROOT9, None, None),
    ("validation-size-warning", f"{T} Validation.test_large_size_is_a_warning_only",
     _state(_body(f"{HOME}#1", fm(f"{HOME}#1", blocked_by=[f"{ECHO}#5"], extra=".size_hours: 12"))), ROOT9, None, None),
    ("references-bare-blocker", f"{T} QualifiedReferences.test_bare_blocker_number_is_invalid", _state(_body(f"{HOME}#1", fm(f"{HOME}#1", blocked_by=["#2"]))), ROOT9, None, None),
    ("references-bare-id", f"{T} QualifiedReferences.test_bare_id_is_invalid", _state(_body(f"{HOME}#1", fm("#1", blocked_by=[f"{ECHO}#5"]))), ROOT9, None, None),
    ("references-retired-version", f"{T} QualifiedReferences.test_retired_schema_is_invalid",
     _state(_body(f"{HOME}#1", fm(f"{HOME}#1", blocked_by=[f"{ECHO}#5"]).replace("issue-dag/2", "issue-dag/1"))), ROOT9, None, None),
    ("references-transferred", f"{T} QualifiedReferences.test_transferred_reference_is_reported", _state(_moved), ROOT9, None, None),
    ("references-mis-cased", f"{T} Trust.test_mis_cased_reference_is_not_reported_as_transferred", _state(_mis_cased), (f"{HOME}#1",), None, None),
    ("resources-none", f"{T} Resources.test_no_resources_means_full_parallelism", _state(base=_frontier("", "")), (), None, None),
    ("resources-overlapping-holds", f"{T} Resources.test_overlapping_holds_conflict",
     _state(base=_frontier(".holds: [host/docker/w/]", ".holds: [host/docker/w/cache]")), (), None, None),
    ("resources-unknown-capacity", f"{T} Resources.test_unknown_semaphore_capacity_is_exclusive", _state(base=_frontier(".meters: [gpu]", ".meters: [gpu]")), (), None, None),
    ("resources-declared-capacity", f"{T} Resources.test_declared_semaphore_capacity_allows_parallel_slots",
     _state(base=_frontier(".meters: [gpu]", ".meters: [gpu]")), (), None, {"gpu": 2}),
    ("resources-multi-slot", f"{T} Resources.test_multi_slot_meter_respects_capacity", _state(base=_frontier(".meters: [gpu*2]", ".meters: [gpu]")), (), None, {"gpu": 2}),
    ("pull-requests-draft", f"{T} PullRequestStates.test_trusted_pr_states_keep_priority_and_render", _state(base=_with_prs([True])), (), None, None),
    ("pull-requests-ready", f"{T} PullRequestStates.test_trusted_pr_states_keep_priority_and_render", _state(base=_with_prs([False])), (), None, None),
    ("pull-requests-draft-and-ready", f"{T} PullRequestStates.test_trusted_pr_states_keep_priority_and_render", _state(base=_with_prs([True, False])), (), None, None),
    ("pull-requests-untrusted-ready", f"{T} PullRequestStates.test_untrusted_ready_pr_does_not_promote_a_trusted_draft",
     _state(lambda s: s["prs"][1].update(isCrossRepository=True), base=_with_prs([True, False])), (), None, None),
    ("pull-requests-active", f"{T} PullRequestStates.test_active_without_a_pr_stays_in_progress", _state(base=_with_prs([], ".status: active")), (), None, None),
    ("pull-requests-draft-not-boolean", f"{T} PullRequestStates.test_missing_or_invalid_draft_state_fails_closed", _state(base=_with_prs([True, "false"])), (), None, None),
    ("trust-untrusted-seed", f"{T} Trust.test_untrusted_seed_is_listed_and_never_a_node",
     _state(_add(f"{HOME}#77", issue(177, "Free money", fm(f"{HOME}#77"), author=STRANGER, association="NONE"))), (), None, None),
    ("trust-untrusted-seed-referenced", f"{T} Trust.test_untrusted_seed_referenced_by_a_trusted_task_blocks_it",
     _state(_all(_add(f"{HOME}#77", issue(177, "Stranger", fm(f"{HOME}#77"), author=STRANGER, association="NONE")),
                 _body(f"{HOME}#2", fm(f"{HOME}#2", blocked_by=[f"{HOME}#1", f"{HOME}#77"])))), (), None, None),
    ("trust-untrusted-editor", f"{T} Trust.test_untrusted_editor_makes_a_trusted_issue_an_opaque_blocker", _state(_edit(f"{HOME}#1", editors=["owner", STRANGER])), ROOT9, None, None),
    ("trust-allowlisted-login", f"{T} Trust.test_allowlisted_login_is_trusted", _state(_edit(f"{HOME}#1", editors=["owner", STRANGER])), ROOT9, {"logins": [STRANGER]}, None),
    ("trust-collaborator-editor", f"{T} Trust.test_collaborator_check_trusts_an_editor",
     _state(_all(_edit(f"{HOME}#1", editors=["owner", "carol"]), _set(collaborators={HOME: ["carol"]}))), ROOT9, None, None),
    ("trust-triage-editor", f"{T} Trust.test_triage_collaborator_is_not_trusted",
     _state(_all(_edit(f"{HOME}#1", editors=["owner", "carol"]), _set(collaborators={HOME: {"carol": "triage"}}))), ROOT9, None, None),
    ("trust-member-association", f"{T} Trust.test_member_association_alone_is_not_trusted",
     _state(_add(f"{HOME}#77", issue(177, "Org member", fm(f"{HOME}#77"), author="pat", association="MEMBER"))), (), None, None),
    ("trust-names-without-case", f"{T} Trust.test_names_compare_case_insensitively",
     _state(_all(_edit(f"{HOME}#1", editors=["owner", "Carol"]), _body(f"{HOME}#1", fm(f"{HOME}#1", blocked_by=["Partner/Lib#1"])),
                 _add("Partner/Lib#1", issue(4242, "Partner lib", fm("Partner/Lib#1"), author="pat", association="OWNER")))),
     ROOT9, {"logins": ["carol"], "owners": ["partner"]}, None),
    ("trust-untrusted-not-planned-blocker", f"{T} Trust.test_closed_not_planned_untrusted_blocker_leaks_no_title",
     _state(_all(_body(f"{HOME}#1", fm(f"{HOME}#1", blocked_by=[f"{ECHO}#5", f"{ECHO}#99"])),
                 _add(f"{ECHO}#99", issue(5099, "t", fm(f"{ECHO}#99"), state="closed", reason="not_planned", author=STRANGER, association="NONE")))), ROOT9, None, None),
    ("trust-association-outside-scope", f"{T} Trust.test_association_only_counts_inside_the_scope",
     _state(_all(_body(f"{HOME}#1", fm(f"{HOME}#1", blocked_by=["mallory/trap#1"])),
                 _add("mallory/trap#1", issue(31337, "Trap", fm("mallory/trap#1"), author=STRANGER, association="OWNER")))), ROOT9, None, None),
    ("trust-owner-widens-scope", f"{T} Trust.test_trust_owner_widens_the_scope",
     _state(_all(_body(f"{HOME}#1", fm(f"{HOME}#1", blocked_by=["partner/lib#1"])),
                 _add("partner/lib#1", issue(4242, "Partner lib", fm("partner/lib#1"), author="pat", association="OWNER")))), ROOT9, {"owners": ["partner"]}, None),
    ("trust-untrusted-root", f"{T} Trust.test_untrusted_root_is_listed_not_a_node",
     _state(_add(f"{HOME}#77", issue(177, "Stranger", fm(f"{HOME}#77"), author=STRANGER, association="NONE"))), (f"{HOME}#77",), None, None),
    ("trust-root-outside-scope", f"{T} Trust.test_root_outside_the_scope_is_refused", _state(), ("mallory/trap#1",), None, None),
    ("trust-untrusted-dependents", f"{T} Trust.test_untrusted_descendants_do_not_inflate_ranking", _state(_stranger_dependents), (), None, None),
    ("trust-fork-pull-request", f"{T} Trust.test_fork_pr_does_not_mark_a_task_in_flight",
     _state(_set(prs=[{"number": 7, "isDraft": True, "url": "u", "author": {"login": STRANGER}, "isCrossRepository": True, "closingIssuesReferences": [closing(2)]}])),
     (), None, None),
    ("trust-same-repository-pull-request", f"{T} Trust.test_same_repository_pr_by_a_trusted_author_marks_in_flight",
     _state(_set(prs=[{"number": 8, "isDraft": False, "url": "u", "author": {"login": "owner"}, "isCrossRepository": False, "closingIssuesReferences": [closing(2)]}],
                 collaborators={HOME: ["owner"]})), (), None, None),
    ("trust-pull-request-by-stranger", f"{T} Trust.test_same_repository_pr_by_an_untrusted_or_missing_author_is_untrusted",
     _state(_set(prs=[{"number": 8, "isDraft": False, "url": "u", "author": {"login": STRANGER}, "isCrossRepository": False, "closingIssuesReferences": [closing(2)]}])),
     (), None, None),
    ("trust-pull-request-without-trust-fields", f"{T} Trust.test_pr_without_trust_fields_is_untrusted",
     _state(_set(prs=[{"number": 9, "isDraft": False, "url": "u", "closingIssuesReferences": [closing(2)]}])), (), None, None),
    ("trust-codeowners", f"{T} Trust.test_codeowners_allowlists_per_repository",
     _state(_all(_edit(f"{HOME}#1", editors=["owner", "carol"]), _edit(f"{ECHO}#5", editors=["owner", "carol"]),
                 _set(codeowners={HOME: {".github/CODEOWNERS": "# owners\n* @carol @flyingrobots/core\ndocs/ docs@example.com\n"}}))),
     ROOT9, {"codeowners": True}, None),
    ("trust-bot-author", f"{T} Trust.test_bot_author_is_untrusted_unless_allowlisted",
     _state(_add(f"{HOME}#77", issue(177, "Automated", fm(f"{HOME}#77"), author="deploy-bot", association="OWNER", author_type="Bot"))), (), None, None),
    ("trust-bot-author-allowlisted", f"{T} Trust.test_bot_author_is_untrusted_unless_allowlisted",
     _state(_add(f"{HOME}#77", issue(177, "Automated", fm(f"{HOME}#77"), author="deploy-bot", association="OWNER", author_type="Bot"))), (),
     {"logins": ["deploy-bot[bot]"]}, None),
    ("trust-bot-editor", f"{T} Trust.test_bot_editor_is_untrusted",
     _state(_all(_edit(f"{HOME}#1", editors=["owner", {"login": "deploy-bot", "type": "Bot"}]), _set(collaborators={HOME: ["deploy-bot"]}))), ROOT9, None, None),
    ("trust-permission-forbidden", f"{T} Trust.test_collaborator_check_that_cannot_run_exits_2",
     _state(_all(_edit(f"{HOME}#1", editors=["owner", "carol"]), _set(collaborators_forbidden=True))), ROOT9, None, None),
    ("trust-edit-history-unreadable", f"{T} Trust.test_null_edit_history_connection_exits_2", _state(_set(graphql_null_edits=True)), ROOT9, None, None),
    ("graph-cycle", "constructed from tests/test_taskalisk.py plan_state: echo#5 waits for home#2, which waits on it through home#1", _state(_cycle), ROOT9, None, None),
]
SCENARIOS = [Graph(name, f"Scenario {name}", ob.from_fake_state(state, roots=list(roots), trust=trust, capacities=caps), None, source=source)
             for name, source, state, roots, trust, caps in SCENARIO_TABLE]
