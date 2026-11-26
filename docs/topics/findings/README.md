# Finding codes

Reference for every code that `issue-dag-core` gives a finding
(`crates/issue-dag-core`, function `findings`). A finding is one violation or
warning of the frontmatter document in an issue body. It carries a code, a
severity, the address of the issue as its subject, and a fixed message that
names keys and rules but never a value or a line of the body.

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

The links go to the copy of the specification vendored in this repository
under `tests/fixtures/issue-dag/`. A code never changes meaning; a rule that
is added gets a new code.

- **error**: a violation. The document is invalid.
- **warning**: the V10 advisory. The document stays valid. A warning is
  reported only for a document with no violations.

A body with no frontmatter block (rules C1 to C3) is not a document and has
no findings. A document gets one finding per rule it breaks, however many of
its values break that rule. Three cases stop judging, so the document gets
one finding only: a line break under C4, a repeated `.dag` (C7), and a `.dag`
that names another format version (P3).

Each example below is the frontmatter block of a case in the vendored
conformance corpus (`tests/fixtures/issue-dag/corpus/cases/document/`), judged
with the address `o/r#1`; the crate's corpus test runs every case.

## Entries

The entries are in the crate's order (`LABELS`), the order of the labels'
text, so `V10` comes before `V2`. The test
`crates/issue-dag-core/tests/finding_reference.rs` fails when a code has no
entry here, or an entry names no code.

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

To fix: migrate to `issue-dag/2`: write every reference as `owner/repo#N` and
set `.dag: issue-dag/2`. The other rules then apply, and may give further
findings.

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
