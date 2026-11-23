# 0002. The output contract is Parley, and the Rust binary inherits it

Status: Proposed in flyingrobots/taskalisk#70 on 2026-11-22, by the agent the owner delegated the
decisions to. Each decision below can be overruled in review; the merge records acceptance.

## Context

[Decision 0001](0001-rust-issue-dag-contract.md) freezes the Python compiler: no new features,
because the Rust rebuild (#25 to #37) replaces it. The compiler printed one indented JSON document
with no declared shape, errors as free text, and exit statuses 1 and 2 with no stated rule. The
house rule is JSON Lines with a declared, separately versioned schema for every message, and the
Parley protocol (flyingrobots/parley, spec 0.2) is that rule written down, with a writer and a
conformance doctor.

The owner made #70 the one exception to 0001 on 2026-11-22: rebuild the output contract once, in
the Python, so that the contract exists before the Rust binary that must emit it.

## Decisions

1. **The Python compiler emits through the vendored Parley writer.** `parley_emit.py` is copied
   unmodified and pinned by digest; a test fails when the copy changes. Nothing the compiler
   computes changes: the result document and its `artifact_hash` are those of 1.x, and the lines
   are a decomposition of that document.
2. **The schemas under `skills/taskalisk/schemas/` are the contract the Rust binary inherits**
   (#58). The Rust binary emits the same message ids at the same versions, with the same line
   order, error codes and exit statuses, and is checked against the same captured runs. A change
   to a message after its first release is a new schema version, never an edit in place.
3. **Line order puts the answer first**: the plan summary, then the frontier in rank order with
   each score term, then the batch, then the detail.
4. **1.x exit 1 becomes 2.** Parley assigns 2 to any reported error; the error's code carries what
   1 used to mean. A usage error is a startup failure, exit 3.
5. **Issue text never enters a receipt.** Bodies are a declared input by id and digest only.
6. **The schemas live inside the skill**, with the repository-root `schemas/` a link to them, so
   an installed skill can answer `--schema` without the repository.

## Consequences

- The skill's release is a breaking change (2.0.0): every agent that parses the 1.x document must
  move to the lines. `SKILL.md` documents the new lines and a recipe for the ranked frontier.
- The installed skill must not be replaced until the release is cut, because running agents read
  the installed copy's output.
- 0001's rule stands for everything else: this exception covers the output only.
