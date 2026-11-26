# Finding codes

Reference for every code that `issue-dag-core` gives a finding: every code of
its public catalogue `CODES`. A finding is one violation or warning. It
carries a code, a severity, the issue that receives it as its subject, for
some codes the reference it concerns, and a fixed message that names keys and
rules but never a value or a line of the body. Four families of findings
and the plan warnings share the catalogue:

- **document findings** (function `findings`): the frontmatter document in an
  issue body, judged with the issue's address;
- **run findings** (function `plan`): the rules of the planning profile that
  discovery and the graph apply to a whole run;
- **body warnings** (function `body_warnings`): Taskalisk's own writing
  convention for a task body, not a rule of any specification.
- **shape warnings** (function `shape_warnings`): Taskalisk's own advisories
  on the shape of a plan's graph, from the skill's doctrine on graph health,
  not a rule of any specification.
- **plan warnings** (function `plan_warnings`): Taskalisk's own advisories on
  a plan as a whole, from the skill's doctrine on graph health. A plan warning
  is not a finding: it concerns no single issue, so it has no subject, and it
  carries a detail of what it measured.

These are the Rust crate's codes. The Python compiler reports frontmatter
problems as `frontmatter.violation` and `frontmatter.warning` lines; their
codes are in the [output reference](../output/README.md#finding-codes).

## How to read a code

A code is `<document>.<label>`. The label is the rule's label, as format rule
V12 assigns it; the prefix names the specification that states the rule:

| Prefix | Specification |
| --- | --- |
| `format.` | the format [`issue-dag/2`](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md): carrier rules C, value rules L, validity rules V |
| `version.` | the [version policy](../../../tests/fixtures/issue-dag/versions.md) |
| `profile.` | the planning profile [`issue-dag-planning/2`](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md) |
| `taskalisk.` | Taskalisk's convention, [Writing a task](../../../skills/taskalisk/WRITING-TASKS.md) for a body warning, or its doctrine, [Core Doctrine](../../../skills/taskalisk/SKILL.md#core-doctrine), for a shape or plan warning; the suffix is a name, not a label |

The links go to the copy of the specification vendored in this repository
under `tests/fixtures/issue-dag/`. A code never changes meaning; a rule that
is added gets a new code. Each code has one severity, which the crate defines
once, in the catalogue:

- **error**: a violation. The document is invalid, or for a run finding the
  run is.
- **warning**: the V10 advisory, a body warning, a shape warning or a plan
  warning. The document stays valid, and a shape or plan warning never makes a
  run invalid. A V10 warning is reported only for a document with no
  violations, body warnings only for a valid task document, and shape and plan
  warnings only for the graph of a run.

A body with no frontmatter block (rules C1 to C3) is not a document and has
no findings. A document gets one finding per rule it breaks, however many of
its values break that rule. Three cases stop judging, so the document gets
one finding only: a line break under C4, a repeated `.dag` (C7), and a `.dag`
that names another format version (P3).

Each example of a document finding is the frontmatter block of a case in the
vendored conformance corpus (`tests/fixtures/issue-dag/corpus/cases/document/`),
judged with the address `o/r#1`; the crate's corpus test runs every case. A
run finding's example names a case under `corpus/cases/graph/`, whose issues
are `o/r#1`, `o/r#2` and so on.

## A reference that cannot be read

A run reports why a reference does not resolve to an issue it can read when
the observations say why. Three causes have a finding of their own:

| Cause | Code | Receives it |
| --- | --- | --- |
| outside the read scope | `profile.D3` | each document that writes it, concerning the reference |
| a pull request | `profile.D4` | the pull request; each open task that writes it in `.blocked_by` also receives `profile.X3` concerning it |
| transferred | `profile.D5` | each document that writes it, concerning the old reference |

A reference in the read scope that resolves to no issue the planner can see
has no finding: rule
[D10](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md#3-discovery)
makes the run incomplete, and the run reports the reason recorded for it. The
bundle records that reason as free text
([OB8](../../../tests/fixtures/issue-dag/corpus/bundle.md#2-observations)), so
the crate does not tell an owner, a repository or an issue number that was not
found apart; that needs a change to the specification first, which is
flyingrobots/taskalisk#126 (decision D17). The test
`crates/issue-dag-core/tests/unreadable_references.rs` pins all four cases.

## Entries

The entries are in the catalogue's order (`CODES`): the document codes in the
order of the labels' text, so `V10` comes before `V2`; then the planning
profile's codes; then the body warnings; then the shape warnings; then the
plan warnings. The test
`crates/issue-dag-core/tests/finding_reference.rs` fails when a code has no
entry here, an entry names no code, or a link or anchor here does not
resolve.

### `format.C4`

**Severity:** error. **Rule:** [C4](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#2-carrier), line breaks.

The block holds a line break the carrier does not allow: a CR not followed by
LF, or one of U+000B, U+000C, U+001C, U+001D, U+001E, U+0085, U+2028 or
U+2029. The lines cannot be told apart reliably, so no other rule is applied
and this is the document's only finding. CRLF line ends are allowed.

Occurs, for example, when a value pasted from elsewhere carries a U+2028 line
separator (case `c4-line-separator`), or a line ends in a lone CR (case
`c4-lone-cr`).

To fix: retype the affected line, or replace the character with a plain line
break (LF) or a space.

### `format.C6`

**Severity:** error. **Rule:** [C6](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#2-carrier), entry lines.

A line of the block is not an entry line (`key: value`, the key in the first
column), not a comment (`#` as its first non-blank character) and not blank.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by:
  - o/r#2
```

The YAML block list is not part of the format: `  - o/r#2` is not an entry
line, and `.blocked_by:` has an empty string as its value, which is not a
list, so this block also gets `format.V5` (case `c6-block-list`). An indented
entry is also not an entry line (case `c6-indented-entry`).

To fix: write one `key: value` per line from the first column, and a list on
one line: `.blocked_by: [o/r#2]`.

### `format.C7`

**Severity:** error. **Rule:** [C7](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#2-carrier), duplicate keys.

Two entry lines have the same key. This applies to free keys as well as `.`
keys.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by: []
area: a
area: b
```

(case `c7-duplicate-free-key`). When the repeated key is `.dag`, the version
is unknown, so no other rule is applied and this is the only finding.

To fix: keep one line per key; join the values of a repeated list key into
one list.

### `format.C8`

**Severity:** error. **Rule:** [C8](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#2-carrier), values.

A value that begins with `[` does not end with `]`.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by: [o/r#2
```

The key of such a line has no value, so a required key written this way is
also absent: this block gets `format.V5` as well (case
`c8-unterminated-key-is-absent`).

To fix: close the list with `]` on the same line.

### `format.L1`

**Severity:** error. **Rule:** [L1](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#4-values-of-format-keys), references.

A value that must be a reference is not of the form `owner/repo#N`, with `N`
from 1 to 2147483647 and no leading zero. This covers `.id` when it is a
string, and the items of `.blocked_by` and `.children`.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by: [#2]
```

A bare `#2` (case `l1-bare-number`) or an issue URL (case
`l1-url-is-not-a-reference`) is not a reference.

To fix: write the reference in full, `owner/repo#N`, even for an issue in the
same repository.

### `format.L2`

**Severity:** error. **Rule:** [L2](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#4-values-of-format-keys), resource keys.

An item of `.holds` is empty.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by: []
.holds: [a,,b]
```

(case `c8-empty-item`). A repeated resource key is allowed (rule V9).

To fix: remove the empty item, or the stray comma.

### `format.L3`

**Severity:** error. **Rule:** [L3](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#4-values-of-format-keys), meter claims.

An item of `.meters` is not a meter claim: `name` or `name*N`, where `name`
uses only ASCII letters, digits, `_`, `.`, `/` and `-`, and `N` is a number
from 1 to 2147483647.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by: []
.meters: [gpu:2]
```

(case `l3-bad-name`). `gpu*0` also fails: zero slots is not a number under L1
(case `l3-zero-slots`).

To fix: write the claim as `name*N`, such as `gpu*2`, or `gpu` for one slot.

### `format.L4`

**Severity:** error. **Rule:** [L4](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#4-values-of-format-keys), integers.

`.size_hours` is an integer below 1 or above 2147483647.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by: []
.size_hours: 0
```

(case `l4-size-zero`; case `l4-size-too-large` has 2147483648).

To fix: give the estimate in whole hours, at least 1. A task above 8 hours
gets the warning `format.V10`.

### `version.P3`

**Severity:** error. **Rule:** [P3](../../../tests/fixtures/issue-dag/versions.md#2-version-policy), of the version policy.

`.dag` names a format version other than `issue-dag/2`: `issue-dag/` followed
by a number. The document is judged under the version policy, not by the
format, so this is its only finding. `issue-dag/1` is retired; any other
version is unknown to this reader.

```yaml
.id: o/r#1
.kind: task
.type: feature
.blocked_by: []
.dag: issue-dag/1
```

(case `p3-retired-version`; case `p3-unknown-version` has `issue-dag/3`).

The fix depends on which case it is; the message is the same for both.

To fix a retired version (`issue-dag/1`): migrate the document to
`issue-dag/2`. Write every reference as `owner/repo#N` and set
`.dag: issue-dag/2`. The other rules then apply, and may give further
findings.

To fix an unknown version (such as `issue-dag/3`): do not rewrite the
document to an older version. It was written for a format this reader does not
know, and the version policy (rules P6 and R1) lets a document declare a
version only once every reader that plans its repository accepts it. Upgrade
Taskalisk to a release that accepts the version. If the number is a typing
error, set `.dag: issue-dag/2`.

### `format.V1`

**Severity:** error. **Rule:** [V1](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#5-validity), version.

`.dag` is absent, is not a string, or is a string that is neither
`issue-dag/2` nor a format name (a format name is `version.P3`).

```yaml
.id: o/r#1
.kind: task
.type: feature
.blocked_by: []
```

(case `v1-version-missing`). `.dag: foo` (case
`v1-version-not-a-format-name`) and `.dag: [issue-dag/2]` (case
`v1-version-as-list`) also give it.

To fix: add the line `.dag: issue-dag/2`.

### `format.V10`

**Severity:** warning. **Rule:** [V10](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#5-validity), advisory.

`.size_hours` is above 8: the task is probably not atomic. The document is
valid. The warning is reported only when the document has no violations.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by: []
.size_hours: 9
```

(case `v10-size-above-eight`; 8 gives no warning, case `v10-size-eight`).

To fix: split the task into tasks of 8 hours or less, or leave it if the
estimate is right and the work cannot be split.

### `format.V2`

**Severity:** error. **Rule:** [V2](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#5-validity), unknown keys.

A key that begins with `.` is not one of the format keys: `.dag`, `.id`,
`.kind`, `.type`, `.blocked_by`, `.children`, `.size_hours`, `.holds`,
`.meters` and `.status`.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by: []
.blockedby: [o/r#2]
```

(case `v2-unknown-format-key`).

To fix: correct the spelling of the key, or drop the leading `.` to make it a
free note, which the format ignores.

### `format.V3`

**Severity:** error. **Rule:** [V3](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#5-validity), identity.

`.id` is absent, or its value is not a string (an integer or a list). A
string that is not a reference is `format.L1` instead.

```yaml
.dag: issue-dag/2
.kind: task
.type: feature
.blocked_by: []
```

(case `v3-id-missing`; `.id: 1` is an integer, case `v3-id-not-a-string`).

To fix: add `.id` with the address of the issue that holds the document,
such as `.id: owner/repo#N`.

### `format.V4`

**Severity:** error. **Rule:** [V4](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#5-validity), kind.

`.kind` is absent, or is not the string `task` or `container`. Without a
valid kind, the keys the kind governs (`.type`, `.blocked_by`, `.children`)
are not judged.

```yaml
.dag: issue-dag/2
.id: o/r#1
.type: feature
.blocked_by: []
.kind: epic
```

(case `v4-kind-other`).

To fix: set `.kind: task` for a unit of work, or `.kind: container` for an
issue that groups others.

### `format.V5`

**Severity:** error. **Rule:** [V5](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#5-validity), task.

A task's keys are wrong: `.type` is absent or not one of `feature`, `bug`,
`decision`, `research`, `investigation`, `spike` or `task`; `.blocked_by` is
absent or not a list; or `.children` is present.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.blocked_by: []
```

(case `v5-type-missing`). `.blocked_by: o/r#2`, a scalar, also gives it (case
`v5-blocked-by-scalar`), as does `.children: []` on a task (case
`v5-task-with-children`).

To fix: give the task a `.type` from the list and a `.blocked_by` list, `[]`
when it has no prerequisite, and remove `.children`.

### `format.V6`

**Severity:** error. **Rule:** [V6](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#5-validity), container.

A container's keys are wrong: `.children` is absent or not a list;
`.blocked_by` is present in any form, `[]` included; or `.type` is present
with a value outside the task types.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: container
.children: [o/r#2]
.blocked_by: []
```

(case `v6-container-blocked-by-empty`; case `v6-container-children-missing`
has no `.children`).

To fix: list the grouped issues in `.children` and remove `.blocked_by`. A
container is not a node (profile rule D9), so put a prerequisite on its child
tasks.

### `format.V7`

**Severity:** error. **Rule:** [V7](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#5-validity), self reference.

An item of `.blocked_by` or `.children` equals `.id`. References compare
without regard to the case of owner and repository.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by: [o/r#1]
```

(case `v7-self-blocked-by`).

To fix: remove the item.

### `format.V8`

**Severity:** error. **Rule:** [V8](../../../tests/fixtures/issue-dag/formats/issue-dag-2.md#5-validity), optional keys.

An optional key has a value of the wrong kind: `.size_hours` is not an
integer, `.holds` or `.meters` is not a list, or `.status` is not `active`,
`parked` or `blocked`. An item of `.holds` or `.meters`, or a `.size_hours`
out of bounds, is `format.L2`, `format.L3` or `format.L4` instead.

```yaml
.dag: issue-dag/2
.id: o/r#1
.kind: task
.type: feature
.blocked_by: []
.status: done
```

(case `v8-status-other`; `.holds: docs`, a scalar, is case
`v8-holds-scalar`).

To fix: correct the value, or remove the key.

### `profile.X1`

**Severity:** error. **Rule:** [X1](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md#4-cross-document-rules), own address, of the planning profile.

`.id` is a reference, but not the address of the issue that holds the
document: the body was copied from another issue, or the issue was
transferred. References compare without regard to the case of owner and
repository. A missing or malformed `.id` is `format.V3` or `format.L1`
instead, and gets no `profile.X1`.

```yaml
.dag: issue-dag/2
.kind: task
.type: feature
.blocked_by: []
.id: o/r#2
```

(case `x1-id-is-not-the-address`, held by `o/r#1`).

To fix: set `.id` to the issue's own address. If the body was copied, check
its other keys too.

### `profile.D3`

**Severity:** error. **Rule:** [D3](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md#3-discovery), out of scope, of the planning profile.

A document names a reference in a repository outside the run's read scope.
The planner never reads it, so it is not a node. Each document that names it
receives this finding, open or closed, and the finding concerns the
reference. A root reference outside the scope rejects the run instead (rule
I2), with no findings.

In case `d3-outside-the-scope`, the read scope is the owner `o`, and `o/r#1`
names `x/y#1` in `.blocked_by`: `o/r#1` receives `profile.D3` concerning
`x/y#1`. The prerequisite is then unknown too, so `o/r#1` also receives
`profile.X3` (case `d3-closed-document-naming-it` shows that a closed
document receives only D3).

To fix: widen the read scope to the repository, if the reference belongs in
the plan, or remove the reference from the document.

### `profile.D4`

**Severity:** error. **Rule:** [D4](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md#3-discovery), pull request, of the planning profile.

A reference resolves to a pull request, not an issue. The pull request is not
a node, and receives the finding itself; it concerns no other reference.

In case `d4-pull-request`, `o/r#1` names `o/r#5` in `.blocked_by`, and `o/r#5`
is a pull request: `o/r#5` receives `profile.D4`, and `o/r#1` receives
`profile.X3` concerning `o/r#5`.

To fix: name the issue the pull request closes instead, since a pull request
is not a unit of planned work.

### `profile.D5`

**Severity:** error. **Rule:** [D5](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md#3-discovery), transferred, of the planning profile.

A reference names an issue that was transferred and now has another address.
It is not a node. Each document that names it receives this finding, which
concerns the old reference; a root reference that no document names receives
it itself.

In case `d5-transferred`, `o/r#1` names `o/r#6`, which was transferred:
`o/r#1` receives `profile.D5` concerning `o/r#6`, and `profile.X3` too. In case
`d5-transferred-root`, the root `o/r#6` receives it.

To fix: replace the old reference with the issue's new address, in every
document that names it and in the run's roots.

### `profile.X2`

**Severity:** error. **Rule:** [X2](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md#4-cross-document-rules), no container prerequisite, of the planning profile.

An item of the `.blocked_by` of an open task names an issue whose document is
a container. A container groups work and is never complete, so it cannot be a
prerequisite: the item makes no edge, and the task receives this finding
concerning the container. A closed task is not checked (case
`x2-closed-task-naming-a-container`).

In case `x2-container-prerequisite`, the open task `o/r#1` names `o/r#9`,
whose `.kind` is `container`: `o/r#1` receives `profile.X2` concerning
`o/r#9`.

To fix: name the container's children that the task actually waits for,
rather than the container.

### `profile.X3`

**Severity:** error. **Rule:** [X3](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md#4-cross-document-rules), unknown prerequisite, of the planning profile.

An item of the `.blocked_by` of an open task names an issue that is neither a
node nor a container: one outside the read scope (D3), a pull request (D4), or
a transferred issue (D5). The task receives this finding concerning that
reference, and the run is invalid. It usually comes with the finding that says
why the reference is not a node.

In case `d4-pull-request`, `o/r#1` names the pull request `o/r#5`: `o/r#1`
receives `profile.X3` concerning `o/r#5`.

To fix: fix the finding that comes with it (see `profile.D3`, `profile.D4` and
`profile.D5`), or remove the prerequisite.

### `profile.G4`

**Severity:** error. **Rule:** [G4](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md#5-the-graph), cycles, of the planning profile.

The `.blocked_by` edges between open nodes form a cycle, so the run is
invalid: no order completes every node. Each node on a cycle, and each node
downstream of one, receives this finding; it concerns no reference. A node
upstream of a cycle does not.

In case `g4-cycle`, `o/r#1` is blocked by `o/r#2` and `o/r#2` by `o/r#1`: both
receive `profile.G4`. In case `g4-downstream-of-a-cycle`, a node that waits on
the cycle receives it too.

To fix: find the cycle among the reported nodes and remove the edge that is
wrong, usually one that points the wrong way. The nodes downstream recover
once the cycle is gone.

### `taskalisk.acceptance-missing`

**Severity:** warning. **Rule:** [Body sections](../../../skills/taskalisk/WRITING-TASKS.md#body-sections), of Taskalisk's convention.

A valid task document's body has no `## Acceptance` heading: a level-2
heading, ATX or setext, whose text is exactly `Acceptance`. The match is
case-sensitive and the heading must be plain text, so `## acceptance`,
`### Acceptance` and `## **Acceptance**` do not count, nor does a heading in a
code block, a block quote or a list.

To fix: add the section from the task's canonical template, with exact and
observable results as a checklist.

### `taskalisk.outcome-items`

**Severity:** warning. **Rule:** [The one-outcome test](../../../skills/taskalisk/WRITING-TASKS.md#the-one-outcome-test), of Taskalisk's convention.

The Outcome section, from its first `## Outcome` heading to the next heading
of level 1 or 2, holds more than one list item, counted at any depth. A task
delivers one outcome; two items usually mean two tasks.

To fix: state the outcome as one sentence. If it needs two, split the task
and give each piece its own issue.

### `taskalisk.outcome-missing`

**Severity:** warning. **Rule:** [Body sections](../../../skills/taskalisk/WRITING-TASKS.md#body-sections), of Taskalisk's convention.

A valid task document's body has no `## Outcome` heading, matched as for
`taskalisk.acceptance-missing`. Without it the outcome checks are skipped.

To fix: add the section from the task's canonical template, with the task's
one outcome as one sentence.

### `taskalisk.outcome-sentences`

**Severity:** warning. **Rule:** [The one-outcome test](../../../skills/taskalisk/WRITING-TASKS.md#the-one-outcome-test), of Taskalisk's convention.

The Outcome section holds more than one sentence, over its prose paragraphs
or within one list item. A sentence ends at `.`, `!` or `?` followed by
whitespace and an uppercase letter, so `e.g. a block` and `v1.2` do not end
one; two paragraphs are two sentences. Code and HTML add no text.

To fix: state the outcome as one sentence with one subject and one verb. Move
detail to Scope, or split the task if the second sentence is a second
outcome.

### `taskalisk.scope-missing`

**Severity:** warning. **Rule:** [Body sections](../../../skills/taskalisk/WRITING-TASKS.md#body-sections), of Taskalisk's convention.

A valid task document's body has no `## Scope` heading, matched as for
`taskalisk.acceptance-missing`. `## Out of scope` is a different section and
does not count.

To fix: add the section from the task's canonical template, listing what the
pull request contains.

### `taskalisk.title-joins`

**Severity:** warning. **Rule:** [Signs of a bundle](../../../skills/taskalisk/WRITING-TASKS.md#signs-of-a-bundle), of Taskalisk's convention.

The issue's title, read as inline Markdown outside code spans, holds a `;` or
the word `and`, in any ASCII case, between two other words: it probably joins
two outcomes. The check runs only when the caller passes the title; the
observation bundle records none.

To fix: if the title names two outcomes, split the task. If `and` is part of
one name, rephrase the title or put the name in a code span.

### `taskalisk.redundant-edge`

**Severity:** warning. **Rule:** [Transitive reduction](../../../skills/taskalisk/SKILL.md#core-doctrine), Core Doctrine 4 of the skill.

An edge of the plan's graph is redundant: the transitive reduction (profile
rule [G5](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md#5-the-graph))
removes it, because a longer path of `.blocked_by` edges between open nodes
already orders the two issues. The warning's subject is the dependent, whose
`.blocked_by` declares the edge; it concerns the prerequisite. Its detail is
the node the edge is implied via: the first child of the prerequisite, in the
text order of references (so `o/r#10` comes before `o/r#2`), other than the
dependent, from which the dependent is reachable. The Python compiler reports
the same edge as `edge.redundant`, with the same `implied_via`.

In a plan where `o/r#2` is blocked by `o/r#1` and `o/r#3` by both, `o/r#3`
receives `taskalisk.redundant-edge` concerning `o/r#1`, implied via `o/r#2`.

To fix: nothing is required; the plan already ignores the edge. Keep it as
evidence, or remove `o/r#1` from `o/r#3`'s `.blocked_by` if it adds nothing.

### `taskalisk.edge-density`

**Severity:** warning. **Rule:** [Edge density](../../../skills/taskalisk/SKILL.md#core-doctrine), Core Doctrine 4 of the skill.

A plan warning, not a finding: it concerns the plan as a whole and has no
subject. The plan's edge density is outside the band the skill states,
`0.01` to `0.50`, both ends included. The density is the number of edges of
the reduced graph (its edges less those the reduction removes, profile rule
[G5](../../../tests/fixtures/issue-dag/profiles/issue-dag-planning-2.md#5-the-graph))
over the number of pairs of open nodes, `n(n-1)/2`, rounded to four decimal
places on its exact decimal value, ties to even, as the Python compiler
computes `edge_density`: 63 edges over 64 open nodes, exactly `0.03125`, is
`0.0312`. The renderer's `edge_density` metric is the same function. A plan with one open
node or none has no pairs and draws no warning. The warning's detail gives
the reduced edges, the open nodes, the density and the band.

Fifteen open tasks with no edges have density `0`, below the band. A chain
of three tasks has two edges over three pairs, `0.6667`, above it. Four tasks
with one edge, `0.1667`, are inside.

To fix: below the band, look for prerequisites that are real but
unrecorded, and propose the edges; many isolated tasks mean the dependencies
have not been recorded, not that the work is independent. Above it, the plan
is close to a single chain: check whether some edges are not true
prerequisites. A small plan can be outside the band for good reason.
