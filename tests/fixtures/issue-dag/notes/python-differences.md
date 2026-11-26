# Differences between the `/2` specification and the Python compiler

This note is informative. It lists every known difference between the `/2`
documents of this repository and the reference implementation, the Python
Taskalisk compiler at `flyingrobots/taskalisk@8e4cb73`
(`skills/taskalisk/scripts/taskalisk.py`). The corpus work
(`flyingrobots/taskalisk#26`) classified each one, in the last column of its
table, as intended legacy behaviour (`legacy`: the rule changes to match), a
defect (`defect`: the implementation is wrong), or a compatibility exception
(`compatibility-exception`: an accepted deviation, recorded with its scope).
No difference is classified as legacy, so no rule changed. The [conformance
corpus](../corpus/README.md) holds a normative case for each difference it
can test, with the same classification (corpus rule CC4).

Differences 1 to 7 were observed on 2026-11-12 by calling the compiler's
parser and validator on constructed bodies, and difference 9 by running the
compiler against its offline fake. Difference 16 was observed on 2026-11-25
by running the compiler's discovery with the GitHub calls stubbed.
Differences 8, 10 to 15, 17 and 18 come from reading the code. On 2026-11-25
the corpus confirmed differences 1 to 10 and 16 by running the compiler at
`flyingrobots/taskalisk@394a5e9`, and found difference 19 among the cases it
added for the amended rule C8; it found no other difference among its
normative cases. On 2026-11-26 the 54 normative cases added for the
[admission policy](../profiles/admission.md) (rules AD1 to AD10,
`flyingrobots/taskalisk#101`) found no difference: the compiler's
`TrustPolicy` makes every decision those rules state, and reads, or leaves
unread, the same lookups. Also on 2026-11-26 the normative cases added for
the amended rules C7 and V10 (`flyingrobots/taskalisk#104`) found
differences 20, 21 and 22, and two more instances of differences 4 and 19.

None of these differences changes the verdict on any document in the
[census of 2026-11-12](../evidence/2026-11-12-frontmatter-shapes.md): the
specification and the Python accept the same 282 documents.

## Format

| # | Input | Specification | Python | Rule | Classification |
| --- | --- | --- | --- | --- | --- |
| 1 | A container with `.blocked_by: []`, `.blocked_by: 0` or an empty `.blocked_by:` | Invalid | Valid: it tests whether the value is falsy, not whether the key is present | V6 | defect |
| 2 | A container with a `.type` outside the enum, such as `.type: zzz` | Invalid | Valid: `.type` is not checked on a container | V6 | defect |
| 3 | `.size_hours`, a reference number or a meter count above 2147483647 | Invalid | Valid: integers are unbounded | L1, L3, L4 | defect |
| 4 | A CR not followed by LF, or U+000B, U+000C, U+001C to U+001E, U+0085, U+2028 or U+2029, inside the block | Invalid | Each is a line break (`str.splitlines`); the result depends on the pieces | C4 | defect |
| 5 | Unicode whitespace other than SP, HT, CR and LF, such as U+00A0, before the opening fence, in a blank line, before a comment or around a value | An ordinary character: before the fence, the body has no frontmatter; elsewhere, part of the line | Whitespace (`\s`, `str.strip`) | C1, C5, C6 | defect |
| 6 | A list item spelled as an integer, such as `.holds: [007]` | The item is the string `007` | The item becomes `7` (`str(int(...))`); `-0` becomes `0` | C8 | defect |
| 7 | A list as the value of `.dag`, `.kind`, `.type` or `.status`, such as `.type: [bug]` | Invalid | The validator raises `TypeError`; the run ends with a traceback and no outcome | V1, V4, V5, V8 | defect |
| 8 | An item of `.blocked_by` or `.children` equal to the issue's address but not to its `.id`, or the reverse | V7 compares with `.id`; X1 reports the address mismatch | The self-reference check compares with the address | V7, X1 | compatibility-exception |
| 19 | A key given twice, where one or both of the lines open a list without closing it, such as `.size_hours: [3` and `.size_hours: 3` | Invalid under C7 and C8: the unterminated line is still an entry line | Invalid under one of them: an unterminated line sets no field, so a later line with the key is no duplicate; a duplicate line is skipped before its list is judged | C7, C8 | compatibility-exception |
| 20 | A key other than `.dag` given twice, such as `.kind: container` then `.kind: task`, `.children` twice on a task, an unknown format key twice, or `.id` twice | The key is judged by C7 alone: no V2, V5, V6 or V7 from it, and a repeated `.kind` or `.id` leaves V5, V6, V7 and X1 unapplied | The first line sets the key and later lines are skipped, so the first value is judged under sections 3 to 5 as well: the labels depend on line order | C7, V12 | compatibility-exception |
| 21 | `.dag` given twice, with another violation in the document | C7 is the document's only violation | The first `.dag` sets the version and the document is judged under it: the other violations, including C6, C8 and P3, are reported beside C7 | C7, V1, V12 | compatibility-exception |
| 22 | An invalid document, including one whose only violation is X1, with a `.size_hours` above 8 | Violations only, no warning | The V10 warning is reported beside the violations | V10 | compatibility-exception |

Difference 1 is the one Decision 7 of the Taskalisk decision record names:
the rule as written stands, and the Python's behaviour is a defect.
Differences 2 to 7 are defects for the same reason: each makes the Python
accept, decode differently or fail to judge a body that the format defines.

Difference 8 is a compatibility exception. Its scope: a document whose `.id`
is not its address. Such a document is invalid under X1 in both, and the same
issue receives the violations, which is what rule F4 makes observable; only
the set of rule labels differs (V7 is added or left out).

Difference 19 is a compatibility exception with the same kind of scope: the
document is invalid in both, and only its set of labels (V12) differs. Where
the key appears once, the Python does what C8 states: the key is absent for
the other rules.

Differences 20 and 21 are compatibility exceptions with the same scope as
difference 19: the document is invalid in both, under C7 in both, and only
its set of labels differs. The specification makes the labels independent of
line order; the Python's depend on it, so `.kind: task` then
`.kind: container` agrees with the specification and the reverse does not.

Difference 22 is a compatibility exception. Its scope: the warnings of an
invalid document. Validity and the violations are the same. The normative
cases `document/v10-invalid-document-has-no-warnings` and
`document/v10-x1-document-has-no-warnings` show it: their expected results
hold `"warnings": []`, which corpus rule CC5 allows and CC8 then compares,
and their twins record the V10 the Python reports. The second is a document
whose only violation is X1, which the Python also does not treat as invalid
for its warnings.

## Planning profile

| # | Situation | Specification | Python | Rule | Classification |
| --- | --- | --- | --- | --- | --- |
| 9 | A document names, in `.blocked_by`, an open issue of the home repository that has no frontmatter, in a run without roots | The issue is an opaque node; the dependent is blocked | The issue is listed as unmodeled and is not a node; the dependent's prerequisite is unknown and the run is invalid | D7, X3 | defect |
| 10 | A `.blocked_by` lists the same closed `not_planned` prerequisite twice | One pair listed for review | One pair per occurrence | G3 | compatibility-exception |
| 16 | Two documents name the same reference outside the scope, or the same transferred reference | Each document that names it receives a violation, whatever the order of visits | Only the documents visited before the reference is reached receive one (`referenced_by[ref] or [nid]`); a later one does not | D2, D3, D5 | defect |
| 18 | A plan with a container | The container is reported with its children | The container is reported without its children: the compiler computes them but `containers_excluded`, and so the `container.excluded` finding, keeps only the identifier, number and title | W1 | defect |

Difference 9 also contradicts `docs/frontmatter-model.md` in Taskalisk,
which says a referenced issue without frontmatter becomes an opaque node. The
specification follows the written rule. It was observed by running the
compiler against the offline fake (`tests/fake_gh.py`) on 2026-11-12: exit 1,
`Unresolved prerequisites`.

Difference 10 is a compatibility exception. Its scope: the list of
not-planned pairs for review (W1). The run's outcome, edges, ready set,
ranking and batch are the same.

Difference 16 is a defect: rule D2 makes the result independent of the order
of visits. The outcome is invalid in both, but a document can be repaired
and the run stay invalid on a violation it was never told about.

Difference 18 is in what the Python reports, not in what it computes; the
corpus's expected results hold the computed plan, so no case shows it.

## Edge edit

| # | Behaviour | Contract | Python | Rule | Classification |
| --- | --- | --- | --- | --- | --- |
| 11 | Order of validation and write | Validate the edited graph in memory, then write | Write the new body, then recompile | E6 | defect |
| 12 | After a failed recompile | Nothing to undo: nothing was written | Write the old body back, which can overwrite a newer edit | E9 | defect |
| 13 | Final reread before the write | Required | Absent | E7 | defect |
| 14 | Writer identity | Checked against the trust policy | Not checked | E7 | defect |
| 15 | Line ends of the block on rewrite | Unchanged | Every line of the block is rejoined with LF | E4 | defect |
| 17 | An edit to a graph that already has another problem | Allowed when the edit adds no new problem (E6a) | An *add* is written, the recompile fails on the old problem, and the old body is written back; a *remove* is written and kept, and the run then reports invalid | E6, E6a | defect |

Differences 11 to 15 and 17 are the subject of `flyingrobots/taskalisk#1`,
whose contract replaces the Python's behaviour. The corpus has no edge-edit
cases, so it does not test them.

## Outside the profile

The Python's `--verify-dag` mode, which compiles a hand-written JSON graph
with soft edges, confidence thresholds and `(merged)` hints, and its
`--repo` inventory mode are not part of the format or the profile. Neither
reads issue frontmatter.
