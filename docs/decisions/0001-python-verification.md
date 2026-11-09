# Make Python verification explicit

Status: accepted implementation direction; adoption is in progress under issue #22.

Taskalisk's existing offline suite checks the CLI through `tests/fake_gh.py`.
It does not enforce the newly adopted lint, strict typing, coverage or source-size
requirements. The first measurement on mainline `4949d4e` passes 89 tests while
the compiler covers 82.51% of statements and 75.28% of branches. These are separate
measurements; a combined coverage total would conceal the branch deficit.

## Decision and compatibility

Keep the dependency-free CLI at `skills/taskalisk/scripts/taskalisk.py`. Move its
existing responsibilities into a sibling `taskalisk_core` package. Separate
process and GitHub adapters, identity/trust checks, frontmatter parsing, graph
analysis, discovery, rendering and command routing. Imports must flow toward
pure domain operations without cycles or hidden mutable registries.

First move the existing definitions without changing their ASTs, preserving
the existing behavioral suite. Then replace imprecise domain types and long
control-flow blocks in separately reviewable commits. Existing defects owned by
#1 and #3 remain in those PRs; this prerequisite does not silently absorb them.
The compatibility promise covers documented CLI behavior and output, not imports
of private functions from the old script.

Use one project-owned uv environment and lock its verification dependencies.
Ruff supplies formatting/lint, Pyright supplies strict checking, Coverage.py
attributes the CLI subprocesses, and Hypothesis supplies bounded property tests.
They are development dependencies only. Coverage.py 7.10.7 and Hypothesis
6.135.26 retain the existing Python 3.9 runtime floor; the newest releases have
higher floors. The lock also captures the type checker's Node runtime.

## Required evidence

Adoption is complete only when the declared runtime matrix passes the locked
checks, each critical component meets separate 95% statement and branch floors,
and other maintained Python meets separate 90% floors. Count executed subprocess
code; reject missing scopes. Define logical-line and nesting measurements and
enforce file/function limits. A percentage never replaces a behavioral oracle.

Demonstrate new gates and load-bearing assertions with specific RED witnesses,
then GREEN on the corrected candidate. Mechanical movement uses structural
comparison plus existing behavior checks; that comparison alone says nothing
about later semantic changes. Test refusal paths alongside valid-path controls.

The fake GitHub adapter is the repository-prescribed offline boundary. It is
not evidence of atomic GitHub writes or of live authentication interoperability.
Read-only backlog compilation remains a separate required integration check.

## Alternatives and consequences

A language port would enlarge the change and introduce another compatibility
problem before the current contracts are measured. Blanket suppressions or a
lowered coverage floor would conceal obligations. Neither is adopted.

Decomposition will require the pending feature branches to merge main and adapt
their changes to the new module ownership. They must rerun their acceptance
checks and receive fresh review on the integrated head. Issue #22 is recorded
as their prerequisite. No new merge waiver is granted by this decision.
