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
| Ruff S603, `StructureScan.test_cli_emits_json_and_exit_status_for_both_control_and_violation` | The interpreter and checker module are fixed; only the owned fixture root varies, without a shell. Module resolution remains part of the trusted checkout boundary. | Real CLI controls check successful and rejected JSON/exit results with a ten-second deadline. | Re-review when command construction, module resolution or fixture ownership changes. |

The machine-readable records in `exceptions.json` own identifiers and expiry.
Registry validation is pending under #22; the file alone is not enforcement.

## Source measurements

Run `.venv/bin/python -m tools.check_structure` from the repository root to emit
JSON measurements, source hashes and exceeded bounds. Taskalisk maintainers own
the check. It scans `.py` and `.pyi` files in all three maintained roots:
`skills/taskalisk/scripts`, `tests` and `tools`. Missing roots, an empty inventory,
more than 1,000 files, unreadable sources or syntax newer than Python 3.9 fail.
Directory enumeration propagates errors and refuses linked subtrees instead of
silently omitting them. Visit at most 1,000 directories per root. This bounds
visited directories, not the standard library's allocation for one directory
listing; execution resource guards remain a separate obligation.
Read only non-symlink regular UTF-8 files, with a one-MiB ceiling per source.
These are local checkout observations, not an atomic filesystem snapshot or a
confinement boundary. Candidate evidence must still match the source it checks.

`source_inventory` owns bounded discovery and file reads. `source_lines` counts
nonblank physical lines carrying code or literal content; real comments do not
count, but a hash inside a string does. Logical function-body lines terminate at
a Python logical newline or a semicolon. Continuation wrapping does not add lines,
and an empty trailing semicolon does not add a statement. Exclude actual leading
docstrings by token span. Include nested declarations and their bodies in the
outer function's source cost; measure those functions separately as well.
Normalize Python's LF, CRLF and CR line endings for analysis, retaining the
original bytes' hash. Convert tokenizer character columns to AST UTF-8 byte
columns before comparing spans. Unicode separators inside literals remain data.

`source_control` counts syntactic nesting of control suites, conditional
expressions and comprehension generators. Sibling `elif` alternatives and the
handlers/cleanup of one `try` stay at the same depth. Each comprehension generator
adds one level; its filters do not add a suite. Nested declarations begin a new
control-depth scope. Count every parameter kind, excluding conventional `self`
or `cls` only on a non-static method. Inspect explicit tuple result alternatives
and direct fixed tuple annotations, including quoted annotations. Homogeneous
variadic tuple annotations describe collections. Type aliases, inferred call
results and decorator aliases remain semantic review boundaries; this check does
not perform type inference or replace strict typing. Ruff C901 separately owns
cyclomatic complexity.

`source_structure` assembles function measurements; `structure_limits` applies
the bounds. Files above 300 lines require locality review, and the 500-line
production / 750-line test ceilings are unconditional. The 200-line file target
is not a hard ceiling. Functions above 40 logical lines need review; above 60
exceed the limit. Other maxima are nesting three, five semantic parameters and
three anonymous tuple fields. Reports identify the path, symbol, source line,
observed value and bound. All findings currently refuse the scan: approved
exception/review matching and CI evidence wiring remain pending under #22.

The tools directory now receives the critical 95% statement and branch floors,
including helpers whose filenames do not begin with `check_`. Passing the source
checker does not establish coverage, rule-registry freshness or complete quality
adoption. Boundary fixtures and deliberate-fault evidence calibrate the checker;
its passing fixture is distinct from the repository's still-failing adoption scan.

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

## Local specification admission

`spec_file` opens `--verify-dag` input without waiting for a FIFO writer, checks
that the opened descriptor names a regular file, and reads at most 32 MiB plus
one byte to detect overflow. A path may be a symlink to a regular file. The
descriptor check avoids a separate path-check/open race; this is not an atomic
snapshot of file contents or a filesystem I/O deadline. Decode strict UTF-8 and
reuse the JSON byte, depth, token, duplicate-key and numeric limits above.

`spec_checks` and `spec_values` validate every consumed field before graph
analysis. Reject malformed input with structured exit 1 and no partial plan.
An empty object still means an empty plan. Node IDs remain arbitrary nonempty
text; dependency objects retain their defaults, and textual dependencies retain
merged hints. `depends_on` wins over `prerequisites`; `holds` wins over `resources`,
including when the primary field is empty or null. Null holds/meters mean none.
Unknown metadata and shadowed aliases remain unused.

Require actual Booleans, finite numeric confidence from zero through one,
positive integral estimates/counts, textual display fields and nonempty resource
names. Nullable URL, milestone and estimate fields remain nullable. Local linked
PR summaries are display data; validation does not establish GitHub trust.

`graph_values` describes admitted graph inputs. Discovery may also retain invalid
frontmatter scalar values alongside violations, so these annotations preserve
diagnostic output instead of laundering invalid fields into valid defaults.
Typing input does not complete source-size or coverage adoption.
The three local-admission modules each require the critical 95% floor.

## Result typing

`discovery_values` records admitted issue evidence, exclusion reasons and public
provenance. Its empty failure variant accompanies recorded lookup errors and is
never compiled. `graph_results` distinguishes a structural graph refusal from a
computed plan. A computed plan may later acquire a false run status because of
frontmatter violations or failed relationship checks; its diagnostic graph data
must remain intact. Render only a computed plan whose run status is successful.

Keep scalar and collection types through analysis, hashing and rendering instead
of using `Any` between individually typed boundaries. Field-value unions retain
invalid frontmatter values for error JSON. Workstream headings format their
values as text; valid inputs retain the same rendering. Explicit field projection
keeps container children out of the public excluded-container summary. These
types neither establish approval nor alter issue #1's write/rollback contract.

## Graph phases

`graph` coordinates four pure phases. `graph_dependencies` owns completion-state
copying, dependency classification and open adjacency. Only admitted open nodes
enter that adjacency; unresolved references and stale merged hints stop analysis.
`graph_structure` owns cycle detection, reachability, transitive reduction and
longest-path depths. Cycle detection precedes all path calculations. The endpoint
invariant removes redundant membership checks during topological traversal.

`graph_ranking` projects source metadata and computed relationships into stable
ranked waves. `graph_resources` allocates the frontier in that order using holds
and semaphore capacities. Keep blocked/opaque exclusions, resource reason priority,
lexical ties and the implicit capacity of one unchanged. Phase records carry
explicit state; source metadata and caller completion sets remain read only.

Generated graph tests use relational closure and bounded path enumeration as
independent oracles for reduction, wave membership and critical-path length.
A named diamond checks redundant-edge evidence and lexical path ties. Fixed
and externally recorded random seeds, shrinking, observed corpus classifications
and deliberate output faults accompany verification. Baseline comparisons cover
complete serialized compiler results and fixed CLI observations, including
provider calls and mutation state. Those comparisons protect compatibility;
agreement with an earlier implementation alone does not establish correctness.

## REST issue field admission

`github_issue_values` admits the REST fields consumed by discovery and author
authorization. Issue numbers must be positive integers; booleans, fractions and
numeric text cannot alias another issue through coercion. Repository identity,
state, title, URL and author association are checked before returning typed
metadata. Preserve nullable body and state-reason fields. A null user remains
unknown and untrusted; a present user needs a nonempty login and exactly `User`
or `Bot` as its actor type. Unsupported types stop the run before any author
association can grant trust.

The REST [issue discriminator](https://docs.github.com/en/rest/issues/issues)
is the presence of a `pull_request` object, including an empty object. Malformed
discriminators are errors. Validate all rows before returning an inventory;
one invalid later row rejects the whole result. Home-list identities must name
the requested repository. Referenced issues preserve their returned identities
for the existing transfer diagnostic. Relationship mirrors use the same checked
identities, so malformed rows cannot silently disappear from comparisons.

These checks validate consumed fields, not every field in GitHub's schema.
They do not add approval, atomic writes or concurrent-body detection; issue #1
retains ownership of the optimistic write contract.

## PR field admission

`github_pr_values` checks the CLI PR inventory before linking. PR and closing-issue
numbers must be positive integers without coercion; every closing reference
requires a repository owner and name. Missing identity never defaults to the
home repository. Require Boolean draft, bot and foreign-branch evidence rather
than interpreting truthiness. Missing/null author or foreign-branch evidence
remains unknown for the trust policy to deny. A present malformed value is a
run error, even on a PR that would otherwise be excluded or has no closing links.

The [GitHub CLI author export](https://github.com/cli/cli/blob/v2.101.0/api/queries_issue.go#L294)
emits `is_bot` and uses `app/` logins for bots. Its
[closing-reference export](https://github.com/cli/cli/blob/v2.101.0/api/export_pr.go#L221)
includes repository owner/name. Fixture examples supply those fields explicitly;
the fake does not silently fill missing values. These references establish the
observed CLI 2.101.0 boundary, not compatibility with every CLI version.

Keep checked domain fields separate from opaque inventory-only wire metadata,
so the public inventory retains its existing shape. Validate every row before
returning any PRs: a malformed later row rejects the whole inventory. These
checks do not add cross-repository fetching or establish completeness of nested
closing-reference pagination; issue #3 owns that discovery work.

## Inventory field admission

`github_inventory_values` checks the fields consumed from `gh issue list` before
returning public summaries. Require a positive integer number, textual title/URL,
an array of named label objects and an explicit nullable milestone. A present
milestone needs a textual title. Preserve label order and discard metadata that
the existing summary never exposed. All issue rows pass or the complete issue
inventory is refused with a source-qualified exit-2 error.

`inventory_values` describes worktree and branch observations without changing
Git command behavior. `authorization_values` types operator trust settings and
the policy explanation; `mutation_values` types existing edit bookkeeping. These
annotations do not strengthen rollback guarantees or replace issue #1's contract.

Inventory CLI tests use real Git in an owned temporary repository with a commit
and `origin/main` baseline. Without that baseline, an unrelated Git error could
make an expected refusal exit code pass accidentally. Tests require the issue
list to be the only reported error and check a valid combined issue/PR summary.

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
