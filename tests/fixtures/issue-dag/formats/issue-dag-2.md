# Format `issue-dag/2`

Status: accepted. This document is the normative definition of the format.

`issue-dag/2` is a format: the typepack `issue-dag@2`, the carrier grammar
below, and the key binding below. It states which issue bodies are valid
documents and the typed record each valid document decodes to. What a set of
documents means as a graph is defined by a planning profile, not here; see
[the `/2` planning profile](../profiles/issue-dag-planning-2.md).

Only statements with a label such as **C3** are normative. Everything else,
including examples and blocks marked *Commentary*, is informative. The key
words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119 and RFC 8174 when
they appear in capitals.

## Example

````markdown
```yaml
.dag: issue-dag/2
.id: flyingrobots/geordi#81
.kind: task
.type: feature
.blocked_by: [flyingrobots/geordi#78, flyingrobots/bunny#199]
.size_hours: 2
area: rust-toolchain.toml
```

## Outcome

The rest of the issue body is free text.
````

This body is a valid document. It decodes to a task record with two
prerequisites, a size of 2 hours and no resources. The key `area` is a free
note and is not part of the record.

## 1. Terms

- A **body** is the text of an issue body as a sequence of Unicode scalar
  values.
- **SP** is U+0020 and **HT** is U+0009. **Blank** means SP or HT.
- **LF** is U+000A and **CR** is U+000D. A **line end** is LF, or CR followed
  by LF.
- To **trim** a string is to remove every leading and trailing blank.
- The **address** of an issue is the reference GitHub gives it: its
  repository's owner and name and its number.

## 2. Carrier

The carrier locates the frontmatter block in a body and splits it into lines.

**C1. Opening fence.** A body has a frontmatter block only if it begins with
zero or more characters from {SP, HT, CR, LF}, then the three characters
`` ``` `` followed by `yaml`, then zero or more blanks, then a line end. That
line is the *opening fence*.

**C2. Closing fence.** A *closing fence* is a line that consists of the three
characters `` ``` `` followed by zero or more blanks, and is followed by a
line end or by the end of the body. The block's content is every line after
the opening fence and before the first closing fence that is not the first
line after the opening fence. A block therefore always has at least one line.

**C3. No block.** A body that does not satisfy C1, or has no closing fence
under C2, has no frontmatter. A body without frontmatter is not a document; it
is neither valid nor invalid. The planning profile says what such an issue
becomes.

**C4. Line breaks.** The content's lines are separated by line ends. If the
content contains a CR that is not followed by LF, or any of U+000B, U+000C,
U+001C, U+001D, U+001E, U+0085, U+2028 or U+2029, the document is invalid.
Its lines cannot be told apart reliably, so no other rule is applied to it:
C4 is its only violation (V12).

**C5. Skipped lines.** A line that is empty or contains only blanks is
skipped. A line whose first character that is not a blank is `#` is a comment
and is skipped. A `#` anywhere else does not start a comment; it is part of
the line.

**C6. Entry lines.** Every other line, after its trailing blanks are removed,
MUST have the form

```text
entry = key *blank ":" *blank value
key   = ["."] ( ALPHA / "_" ) *( ALPHA / DIGIT / "_" / "-" )
value = *char
```

where ALPHA and DIGIT are ASCII letters and digits and `char` is any character
other than a line end. The key starts in the first column. The value is
trimmed. A line that has another form makes the document invalid.

**C7. Duplicate keys.** If two entry lines have the same key, the document is
invalid. This applies to free keys as well as `.` keys. Such a key is
*repeated*. A repeated key is present, but it has no value, and no rule of
sections 3 to 5 judges it, its values or a requirement that depends on its
value: it receives no label from those sections, whatever its lines hold and
in whatever order they come. So a repeated format key outside M2 is labelled C7, not V2;
a repeated key that a rule requires is present, so it is not absent under
that rule; a repeated key that a rule forbids, such as `.children` on a task,
is labelled C7, not V5 or V6; a repeated `.kind` leaves the kind unknown, so
V5 and V6 are not applied; and a repeated `.id` leaves the identity unknown,
so V3, V7 and X1 are not applied. Where C7 and a rule of sections 3 to 5
would both judge a repeated key, C7 governs. Each line of a repeated key is
still a line of the block, and is still labelled under C6 and C8 when it
fails them.

A repeated `.dag` leaves the document's version unknown, so no format
applies to it: C7 is the document's only violation, and no other rule,
including C6 and C8 on its other lines, is applied to it. Every other
repeated key is judged key by key as above. A document that fails C4 is not
read into lines, so C4 remains its only violation even when a key would be
repeated.

**C8. Values.** A trimmed value is a list or a scalar.

- If it begins with `[`, it is a list, and it MUST end with `]`; otherwise the
  document is invalid. The text between the brackets is the *inner text*. If
  the trimmed inner text is empty, the list is empty. Otherwise the inner text
  is split at every `,`, and each part is trimmed and then unquoted under C9 to
  give one item. Every item is a string. A comma cannot occur inside an item,
  quoted or not. An entry line whose value begins with `[` and does not end
  with `]` is still an entry line, so C7 applies to its key, but it gives its
  key no value: for the rules of sections 3 to 5 the key is absent unless
  another entry line gives it a value, or the key is repeated (C7), in which
  case it is present.
- Otherwise it is a scalar. A scalar is unquoted under C9. If the scalar was
  not quoted and consists of an optional `-` followed by one or more ASCII
  digits, it is an *integer*, whose value is the decimal number it spells.
  Leading zeros are allowed. Any other scalar is a *string*.

**C9. Quotes.** A text of two or more characters whose first and last
characters are both `"` or both `'` is quoted; its unquoted form is the text
without those two characters. There are no escape sequences. The quote
character MAY occur inside the unquoted form. Any other text is its own
unquoted form.

**C10. No null.** The carrier has no null and no boolean. `null`, `~`,
`true` and an empty value are strings. A key that does not appear is
*absent*, and absence is distinct from an empty list.

> *Commentary.* The info string is `yaml` because GitHub renders the block
> well, but the grammar is a small, fixed subset. Block lists, flow mappings,
> multi-line values, anchors and escapes do not exist. Pinning the subset is
> what lets two independent readers agree on every body.
>
> C2's odd case is deliberate. A body that begins
> `` ```yaml `` followed at once by `` ``` ``, with no later closing fence, has
> no frontmatter, as in the reference implementation, rather than an empty
> block. When a later closing fence exists, the block runs to it and its first
> line is the `` ``` ``, which makes it invalid.

## 3. Key binding

**M1.** A key that begins with `.` is a *format key*. A key without the
prefix is a *free key*.

**M2.** The format key `.` followed by a field name binds to that field of
the typepack's shape. The format keys of `issue-dag/2` are exactly `.dag`,
`.id`, `.kind`, `.type`, `.blocked_by`, `.children`, `.size_hours`, `.holds`,
`.meters` and `.status`.

**M3.** A free key and its value are notes for people and agents. They MUST
be syntactically valid under section 2, and are otherwise ignored. They are
not part of the record.

## 4. Values of format keys

**L1. References.** A reference is written `owner/repo#N`. After trimming, it
MUST match

```text
reference = name "/" name "#" number
name      = 1*( ALPHA / DIGIT / "_" / "." / "-" )
number    = %x31-39 *DIGIT
```

and `number` MUST be at most 2147483647. Two references are equal when their
numbers are equal and their owner and repository names are equal without
regard to ASCII case. The *canonical form* of a reference writes the owner and
repository in ASCII lower case. A bare `#N` or `N` is not a reference.

**L2. Resource keys.** A resource key is a non-empty string.

**L3. Meter claims.** A meter claim is `name` or `name*N`, where `name` is
one or more characters from ASCII letters, digits, `_`, `.`, `/` and `-`, and
`N` is a number as in L1. `name` alone claims 1 slot.

**L4. Integers.** An integer value of `.size_hours` MUST be at least 1 and at
most 2147483647.

## 5. Validity

A document is the set of entries of one frontmatter block. It is *valid*
under `issue-dag/2` when it satisfies every statement of sections 2 to 5.
Each failure is a *violation*.

**V1. Version.** `.dag` MUST be present, and its value MUST be the string
`issue-dag/2`. A document whose `.dag` names another version is judged under
the [version policy](../versions.md), not by this document. A document whose
`.dag` is repeated names no version; C7 is its only violation.

**V2. Unknown keys.** A format key that is not listed in M2 is a violation.

**V3. Identity.** `.id` MUST be present and MUST be a reference.

**V4. Kind.** `.kind` MUST be present and MUST be the string `task` or
`container`.

**V5. Task.** When `.kind` is `task`:

- `.type` MUST be present and MUST be one of the strings `feature`, `bug`,
  `decision`, `research`, `investigation`, `spike` or `task`;
- `.blocked_by` MUST be present and MUST be a list, possibly empty, whose
  every item is a reference;
- `.children` MUST be absent.

**V6. Container.** When `.kind` is `container`:

- `.children` MUST be present and MUST be a list, possibly empty, whose every
  item is a reference;
- `.blocked_by` MUST be absent, in any form, including `[]`;
- `.type` MAY be present; if it is, it MUST satisfy the value rule of V5.

**V7. Self reference.** No item of `.blocked_by` or `.children` may equal the
value of `.id`.

**V8. Optional keys.** Each of the following MAY be absent. When present:

- `.size_hours` MUST be an integer under L4;
- `.holds` MUST be a list whose every item is a resource key;
- `.meters` MUST be a list whose every item is a meter claim;
- `.status` MUST be the string `active`, `parked` or `blocked`.

These keys are valid on a container as well as on a task.

**V9. Duplicate items.** A reference or resource key MAY occur more than once
in one list. It does not make the document invalid.

**V10. Advisory.** A `.size_hours` above 8 is reported as a warning: the
task is probably not atomic. A warning never affects validity. Warnings are
reported only for a document that has no violation at all, including the
violation of profile rule X1 when the document is judged with its issue's
address: a document with any violation has violations and no warnings,
whatever its `.size_hours`.

**V11. No trust.** No format key carries trust, approval, a signature or an
identity of a person. Whether an issue may be read as a document at all is
decided outside the document; see the planning profile.

**V12. Labels of violations.** A document receives one violation for each
requirement it fails (except under C4, which stops the reading, and under C7
for a repeated `.dag`, which stops the judging), and each violation carries
the label of exactly one rule, the rule that states the requirement most
specifically:

- a line of the block that fails C4, C6, C7 or C8 is labelled with that rule;
- a repeated key is labelled C7 and receives no label from the bullets
  below, which apply only to keys that are not repeated (C7); its lines are
  still labelled under C6 and C8;
- a format key outside M2 is labelled V2;
- an absent `.dag`, or a `.dag` that is not a string, is labelled V1. A
  `.dag` string other than `issue-dag/2` is labelled P3 when it is a format
  name, `issue-dag/` followed by a number as in L1, and V1 otherwise;
- an absent `.id`, or one that is not a string, is labelled V3; a string that
  is not a reference is labelled L1;
- an absent, extra or wrongly kinded value of `.kind`, `.type`,
  `.blocked_by`, `.children`, `.size_hours`, `.holds`, `.meters` or
  `.status`, or a string outside its values, is labelled with the rule that
  requires it: V4 for `.kind`, V5 for a task's keys, V6 for a container's
  `.blocked_by`, `.children` and `.type`, V8 for the optional keys. A scalar
  where a list is required, a list where a scalar is required, and a string
  where an integer is required are wrongly kinded;
- an item of a list, or an integer, whose form fails L1, L2, L3 or L4 is
  labelled with that rule;
- a self reference is labelled V7;
- when the document is judged with its issue's address, a `.id` reference
  that is not that address is labelled X1 (profile rule X1).

Each label is reported once for a document, however many of its values fail
the rule. A warning under V10 carries the label V10.

> *Commentary.* V3 and L1 check only `.id` itself. Whether `.id` names the
> issue that holds the document needs the issue's address, which is an
> observation, so the rule is in the planning profile (rule X1). Conformance
> cases at document level carry the address, so they test both.

## 6. Record

**M4.** A valid document decodes to exactly one record. Two documents with
equal records have the same decoded meaning.

| Field | Value |
| --- | --- |
| `version` | `issue-dag/2` |
| `id` | The `.id` reference, in canonical form |
| `kind` | `task` or `container` |
| `type` | The `.type` string, or none when absent |
| `blocked_by` | For a task, the `.blocked_by` references in canonical form, in written order, duplicates kept; for a container, none |
| `children` | For a container, the `.children` references in canonical form, in written order, duplicates kept; for a task, none |
| `size_hours` | The integer, or none when absent |
| `holds` | The set of `.holds` keys; empty when absent |
| `meters` | The `.meters` claims as `(name, slots)` pairs, in written order; empty when absent |
| `status` | The `.status` string, or none when absent |

Free keys, comments, blank lines, key order, spacing, quoting and line ends
are not part of the record.

## 7. Typepack

The shape and laws of `issue-dag@2` are in
[`typepacks/issue-dag@2`](../typepacks/issue-dag@2/). They are checked with a
pinned Wesley (`WESLEY.json` there, `scripts/check_typepack.py`): the shape is
within the dialect of [versions.md](../versions.md) A6, and the laws are bound
to it. They are not normative: where they and this document differ, this
document governs.
