# Edge edit: write and concurrency contract

Status: accepted. This document is normative for any program that changes a
`.blocked_by` list of an `issue-dag/2` document on GitHub. It specifies the
contract of `flyingrobots/taskalisk#1`.

Only statements with a label such as **E4** are normative. Everything else,
including blocks marked *Commentary*, is informative. The key words MUST,
MUST NOT, SHOULD and MAY are used as in RFC 2119 and RFC 8174 when they
appear in capitals.

## Layers

| Layer | Edge edit |
| --- | --- |
| Logical operation | Add one reference to, or remove one reference from, the `.blocked_by` of one task |
| Transport operation | Replace the whole issue body with one update request |
| Concurrency contract | E8: what is preserved, when the write is refused, and what is not protected |

A narrow logical operation does not narrow its effect. The write replaces the
entire body, so the contract is stated for the body.

## Rules

**E1. Operation.** An edge edit names a *parent* and a *child*, both
references. *Add* makes the parent a prerequisite of the child. *Remove* takes
every occurrence of the parent out of the child's `.blocked_by`. A parent
equal to the child is refused.

**E2. Scope.** The child MUST be in the read scope. For *add*, the parent
MUST also be in the read scope. For *remove*, the parent need not be: removing
a reference to an issue outside the scope is how such a reference is repaired.

**E3. Child.** The child MUST resolve to an issue, not a pull request. It
MUST be admitted under the trust policy that plans its repository. Its body
MUST hold a valid task document, judged under the format and under the
profile's rule X1.

**E4. Rewrite.** The new body is the old body with exactly one line changed:
the single line of the frontmatter block whose key is `.blocked_by`. That line
becomes

```text
.blocked_by: [<r1>, <r2>, …]
```

where the references are the child's existing `.blocked_by` references in
canonical form and in their written order, with the parent appended at the
end for *add* when no existing reference equals it, and with every reference
equal to the parent left out for *remove*. An empty list is written `[]`.
Every other character of the body, including line ends, is unchanged. If the
block does not have exactly one line whose key is `.blocked_by`, the edit is
refused.

**E5. No-op.** If the new body equals the old body, nothing is written.

**E6. Validate before writing.** Before any write, the program MUST compile
the closure with the proposed edit applied in memory, under the profile in
use, with the child included even when the run's roots do not reach it, and
compile it once more without the edit. The edit is refused, and nothing is
written, when the compilation with the edit is incomplete (an observation is
unavailable), or when it has a cycle, a violation, a reference outside the
scope or an unknown prerequisite that the compilation without the edit does
not have (E6a). A problem that is already there does not refuse an edit that
leaves it unchanged or removes it, so one repair can be applied while another
problem remains.

**E6a. What is new.** A violation is identified by the issue that receives
it, the label of the rule that gives it, and the reference or key it
concerns; it is new when the compilation without the edit has no violation
with the same three. Message text is not part of the identity. An *add* of
the edge from parent `p` to child `c` creates a cycle exactly when `p` is
reachable from `c` in the graph of the compilation with the edit, with that
one edge left out. That compilation is used, not the one without the edit,
because the edit can bring into the closure issues that a rooted run did not
reach before. A *remove* never creates one. A cycle among issues that only
the compilation with the edit reaches also counts as new, as a violation on
such an issue does: the edit is what brings either into the plan. A reference
outside the scope is new when the compilation without the edit does not name
it from the same document, and so is an unknown prerequisite (X3), which
makes a run invalid without being a violation.

**E7. Writer and final reread.** Before the write, the program MUST check
that the identity it writes as is admitted under the same trust policy, and
refuse an unknown or untrusted writer. Immediately before the write, it MUST
read the child again and refuse the write if the child's address, its body,
or the admission of its body's editors differs from what E3 and E6 validated.

**E8. Concurrency contract.** An edit to the child made before the final
reread of E7 is preserved, or the write is refused. An edit made between that
reread and the write can be lost. A change to another issue after E6 can make
the graph cyclic or invalid; the next plan reports it. No other guarantee is
given.

**E9. No restoration.** After a write is sent, the program MUST NOT write the
issue body again to restore an earlier body, and MUST NOT retry a failed or
uncertain write. It reports the failure.

**E10. Outcome.** A refusal for a conflict or a rule is an *invalid* outcome
that names the issue. A refusal because an observation was unavailable is an
*incomplete* outcome. In both cases nothing was written.

> *Commentary.* GitHub documents no conditional update for issues, so a
> reread followed by an update is not atomic, and E8 states what remains. The
> program states this limit in its own guidance and does not promise more.
>
> The reference implementation at `flyingrobots/taskalisk@8e4cb73` does not
> conform. It writes the new body first, recompiles, and on failure writes
> the old body back, which can overwrite a newer edit and leaves a cycle in
> the truth source for the length of the recompile. It rewrites the block
> with LF line ends. Its replacement is `flyingrobots/taskalisk#1`.
