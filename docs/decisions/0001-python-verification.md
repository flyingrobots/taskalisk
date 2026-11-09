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

The adoption matrix covers CPython 3.9 through 3.13 on macOS and Linux, with
explicit patch pins in CI and 3.13.15 for local development. Later minors and
other platforms are unclaimed. Metadata uses `>=3.9,<3.14` to express this
finite range; the CLI's minimum is unchanged. Compatibility remains pending
until the matrix runs on the actual candidate. The setup step uses uv 0.12.19;
ordinary checks use the prepared environment without syncing it again.

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

`tests/fixture_models.py` describes synthetic fixture construction, and
`fixture_builders.py` owns the reusable frontmatter, issue and backlog builders.
These types do not admit external data into production. Fault-injected wire
fields, such as a deliberately non-boolean PR draft state, remain `object` until
the actual adapter checks them. Moving builder options preserves the existing
values and call arguments through differential output and normalized AST checks.

The fake provider's entrypoint routes through `fake_api` and `fake_history`;
`fake_fixture` owns state I/O and issue projection. `fake_values` checks decoded
containers and scalar types independently of production admission code. Values
inside wire records remain `object` where fault injection intentionally permits
malformed responses. Copied fixture mappings are written back explicitly before
saving mutations. Provider typing does not prove fidelity to GitHub; the separate
101-editor contract checks that the fake honors the query's `first:100` limit.

## Alternatives and consequences

A language port would enlarge the change and introduce another compatibility
problem before the current contracts are measured. Blanket suppressions or a
lowered coverage floor would conceal obligations. Neither is adopted.

Decomposition will require the pending feature branches to merge main and adapt
their changes to the new module ownership. They must rerun their acceptance
checks and receive fresh review on the integrated head. Issue #22 is recorded
as their prerequisite. No new merge waiver is granted by this decision.

## Narrow lint decisions

Approving owner: Codex, exercising James's delegated implementation decisions.
These decisions concern diagnostics that conflict with the chosen, tested boundary;
they do not waive typing, coverage, source limits or behavioral checks.

| Diagnostic and scope | Reason and risk | Compensating verification | Review condition |
| --- | --- | --- | --- |
| Ruff PT009, TestCase assertions in `tests/*.py` | The local policy prescribes unittest. Native assertions preserve its diagnostics and subtest behavior; no product assertion is exempted. | Diagnostic RED runs exercise the actual assertions. | Remove if the repository changes test frameworks; review with every lint-policy update. |
| Ruff PT027, TestCase exception assertions in `tests/*.py` | The same local unittest contract requires native exception assertions without a second framework. | Invalid-limit tests check the exact exception family and diagnostic, with deliberate acceptance faults. | Remove if the repository changes test frameworks; review with every lint-policy update. |
| Ruff S603, the marked coverage-gate test invocation | The executable and checker are fixed; only owned fixture paths vary. A changed command producer could invalidate that assumption. | Tests invoke the real checker with a fixed argument vector and timeout, without a shell. | Remove or re-review if the command or path producer changes. |
| Ruff T201, marked coverage-checker prints | These lines intentionally emit CLI diagnostics. Unintended payload disclosure remains a review concern. | CLI tests assert specific failures; output contains coverage paths and counts. | Re-review when the output contract changes. |
| Ruff S603, `process_capture.run_limited` | Internal callers supply executable argument vectors without a shell. A compromised executable or PATH remains outside the I/O guard's boundary. | Real local-process tests exercise bounded I/O, refusal and cleanup. | Re-review when command producers or executable resolution change. |
| Ruff S603, `FakeGh.run_fake` | The test invokes the fixed Python interpreter and owned fake-provider file, without a shell. A change to either path would change this assumption. | Provider-contract tests use a five-second deadline and check pagination, termination and invalid fixture limits. | Re-review when command construction or fixture ownership changes. |

The machine-readable records in `exceptions.json` own identifiers and expiry.
Registry validation is pending under #22; the file alone is not enforcement.

## Command ownership

The command adapter targets POSIX hosts (macOS and Linux). Other hosts refuse
before launching a child. Each command has a 60-second deadline and a 32-MiB
ceiling for input and for combined stdout/stderr. UTF-8 decoding is strict;
exceeded output is discarded rather than admitted as a partial JSON response.
Input admission occurs before spawn. There is no implicit retry.

One process group owns each command and its ordinary descendants. On every
exit the supervisor terminates that group and reaps its leader. Orphan reaping
belongs to the operating system. A process that deliberately detaches from the
group, and any already-submitted remote operation, can outlive this boundary.
The guard is not an execution sandbox. Cleanup failure is raised explicitly.
Issue #1 owns optimistic mutation reconciliation; a local timeout cannot prove
that GitHub rejected a write.

Exit observation uses Linux `waitid(WNOWAIT)` or macOS kqueue so the leader
remains unreaped until group shutdown. Python exposes macOS `waitid` only from
3.13, so using it unconditionally would break the preserved runtime floor.
Reaping first could release the numeric identity before its last use. The
adapter owns this child exclusively; an unrelated signal handler must not reap
it. Tests observe the child as still waitable after capture and verify that
group shutdown releases a separate descendant's kernel lock.

Darwin may return EPERM when only the exited leader remains in the group. On
that path, cleanup reaps the leader and probes group existence with signal 0.
Only an absent group completes cleanup. A remaining or inaccessible group is
an error; no terminating signal is sent after the identity has been released.

## GitHub JSON admission

Decode external JSON into `object`; domain adapters must check fields before
assigning domain types. An object-container check establishes string keys only,
not the meaning of its values. Duplicate keys, non-finite numbers, numeric tokens
longer than 128 characters and lone Unicode surrogates are rejected. These
otherwise permissive decoder behaviors can conceal or change trust evidence.

Apply ceilings of 32 MiB of UTF-8 input, 32 container levels and 100,000 structural
punctuation tokens outside strings. Check the envelope before decoding; quoted
punctuation and escapes do not consume the structural budget. Callers may tighten
these ceilings. They bound parsing work and allocation inputs, not process memory.

A list response must contain only objects. Missing output is an error; a literal
empty array is a successful empty list. Paginated arrays admit all pages or none:
an invalid later page records a source-specific error and discards earlier rows.
Only JSON whitespace separates pages. Generic `null` remains a JSON value and
is distinct from failure through the error collection; domain adapters decide
whether a nullable field is valid. CLI witnesses check that malformed issue-list
bytes reach structured exit 2 instead of hiding work behind an empty frontier.

## Edit-history field admission

`github_history_values` validates the nested GraphQL envelope, textual body,
editor records and pagination metadata before assigning domain types. Null
nodes and null editors remain unknown identities for the trust policy to deny.
An actor object requires a nonempty login and a supported `User` or `Bot` type.
Other actor types stop the run; their identity semantics must be specified before
they can share an authorization path. A response carrying GraphQL errors is
incomplete even when it also contains usable-looking data.

`github_history` owns pagination. Require a boolean `hasNextPage` and a nullable
text cursor; continuation requires a nonempty, previously unseen cursor. Cap each
history at 100 pages and 10,000 editor records. A nonterminal last allowed page
fails before another request. Each command retains the command adapter's own
deadline; these aggregate count limits do not impose a total elapsed deadline
on an entire backlog compile. Stop on any malformed or incomplete page, record
exit-2 run errors and return no history prefix. Preserve issue #1's ownership of
detecting a body change across otherwise valid pages.

The [GitHub schema](https://docs.github.com/en/graphql/reference/users#usercontenteditconnection)
declares pagination metadata non-null while allowing nullable nodes and editors.
The null-versus-malformed distinction is deliberate. The current supported
actor set is narrower than GitHub's complete Actor interface; an unsupported
actor stops the run rather than being reinterpreted as a human.
