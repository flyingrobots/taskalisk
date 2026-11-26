# Output contract

Reference for what `skills/taskalisk/scripts/taskalisk.py` writes. Every line on stdout and
stderr is one JSON object that conforms to the [Parley protocol](https://github.com/flyingrobots/parley)
(spec 0.2) and names its schema in `_schema`. The schemas are under `skills/taskalisk/schemas/`
(the repository-root `schemas/` is a link to that directory, so the installed skill carries them).
The decision behind this page is [0002](../../decisions/0002-parley-output-contract.md); the
requirements and their tests are the [test plan](test-plan.md).

## The writer

Lines are written by `skills/taskalisk/scripts/parley_emit.py`, the Python Parley writer, copied
unmodified from flyingrobots/parley's release `parley-emit-py-v0.3.0` (version 0.3.0, Parley spec 0.2.1).
`parley_emit.pin.json` beside it records its SHA-256 and that commit. Two checks hold it:

- **Drift** (offline, every run of the suite): `Vendored.test_copy_matches_its_pin` fails when the
  copy's digest or size differs from the pin. It proves only that copy and pin agree; both live
  here, so a changed writer with a recomputed pin passes it.
- **Provenance** (needs the network; CI runs it): `python3 scripts/check_vendored_writer.py` fetches
  `packages/parley-emit-py/parley_emit.py` from flyingrobots/parley at the pinned commit and
  requires its digest and size to equal the pin's and the copy's. A failed fetch is a failure. In
  the offline suite its test (`TASKALISK_UPSTREAM_CHECK=1` to run it) is reported as skipped;
  `-v` shows why. The pin must name a full 40-character commit: a short SHA or a branch is a
  moving target, and is refused before anything is fetched.

`python3 parley_emit.py --vendor-info` prints the digest and a `shasum -c` command. The writer is
Apache-2.0; its `LICENSE` and `NOTICE` sit beside it.

The writer owns the envelope (`event`, `t`, `seq`, `run`, `_schema`), the bootstrap line, the
receipt, redaction, `--help`, `--schema`, `--human`, `--dry-run`, the top-level handler and the
exit status. The compiler owns the result messages below.

## Commands

| Command | Selected by (1.x flag) | Reads | Writes |
| --- | --- | --- | --- |
| `plan` | `--from-github` | issues, edit history, pull requests, permissions, CODEOWNERS, local branches | nothing |
| `edit` | `--add-edge` or `--remove-edge` | as `plan` | the child issue's body (its `.blocked_by` line) |
| `verify` | `--verify-dag FILE` | the file | nothing |
| `inventory` | no mode flag | git worktrees and branches, open pull requests and issues | nothing |

Inventory applies no trust gate: its `inventory.issue` and `inventory.pull_request` lines, and its
receipt, carry every open issue and pull request as GitHub returns it, strangers' titles, authors and
fork branch names included (threat model C3). The trust gate applies to `plan`, `edit` and `verify`.

A command may be named, as the first argument (`taskalisk.py plan --root ...`); only that argument is
taken as the command, so a flag value such as `--reason edit` is the flag's. When none is named, the 1.x mode
flag selects it and the receipt's `argv` shows the command put first, with a step saying it was
inferred. A bare `--help` or `--schema` describes every command.

## Messages

Each message type is versioned on its own, independently of the compiler's version (`2.0.0`).
All are drafts at `1.0.0` until a release names them in `CHANGELOG.md`.

| `_schema.id` | Version | `event` | One line per |
| --- | --- | --- | --- |
| `taskalisk.plan` | 1.0.0 | `plan` | plan (always first among a plan's results) |
| `taskalisk.frontier_node` | 1.0.0 | `frontier_node` | Wave 0 node, rank 1 first |
| `taskalisk.batch` | 1.0.0 | `batch` | plan that compiled |
| `taskalisk.frontier_change` | 1.0.0 | `frontier_change` | change found by `--since-last` |
| `taskalisk.node` | 1.0.0 | `node` | node in Wave 1 or later |
| `taskalisk.wave` | 1.0.0 | `wave` | wave, with its ids in rank order |
| `taskalisk.edge` | 1.0.0 | `edge` | edge of the reduced graph, with its evidence |
| `taskalisk.finding` | 1.0.0 | `finding` | thing a reader must see (codes below) |
| `taskalisk.rendering` | 1.0.0 | `rendering` | `--emit-roadmap` or `--emit-mermaid`, text in `text` |
| `taskalisk.edge_edit` | 1.0.0 | `edge_edit` | edit (first among an edit's results) |
| `taskalisk.inventory.summary` | 1.0.0 | `inventory.summary` | inventory (first) |
| `taskalisk.inventory.worktree` | 1.0.0 | `inventory.worktree` | worktree |
| `taskalisk.inventory.branch` | 1.0.0 | `inventory.branch` | unmerged branch (`scope` local or remote) |
| `taskalisk.inventory.pull_request` | 1.0.0 | `inventory.pull_request` | open pull request |
| `taskalisk.inventory.issue` | 1.0.0 | `inventory.issue` | open issue |

Errors and warnings are the writer's `parley.error` (2.0.0) and `parley.warning` lines on stderr;
discovery is `parley.command` and `parley.schema`; a usage error is `parley.startup.failed`.

### Line order, and why

A plan's stdout is: the bootstrap line; `edge_edit` (an edit only); `plan`; every
`frontier_node` in rank order; `batch`; any `frontier_change`; then `node`, `wave`, `edge`,
`finding` and `rendering`; `end` last. Errors follow the results on stderr.

The plan line is first because it is the smallest thing that answers "what next": its `frontier`
and `batch` list the ids in rank order, and its `ok` says whether they can be trusted. A caller
that wants only that reads two lines and stops. The frontier nodes come next because the next
question is "why this order", which their `score` answers. The batch follows the frontier it is
drawn from. Everything after it is detail for audit and rendering, which most callers skip.

### The plan line

`mode` is `github` or `dag_spec`. `outcome` is `compiled`, `cycle` or `unresolved`; only a
compiled plan has `metrics`, `frontier`, `batch` and `open_frontier_count`, and only it is followed
by node, batch, wave and edge lines. `ok` is false when the plan did not compile or the run
reports an error (invalid frontmatter in the closure, a failed relationship lookup); then
`error_codes` lists the errors in the order they follow, and **nothing may be dispatched from the
plan**. `source` (github mode) holds the repository, the roots and the trust in force.

### A frontier node's score

`priority_score` is unchanged from 1.x. `score.terms` states it:

| Term | Value | Weight |
| --- | --- | --- |
| `in_flight` | 1 when the status is `wip`, `in-review`, `in-progress`, `active` or `ready-to-merge` | 1000 |
| `parked` | 1 when the status is `parked` | 500 |
| `descendants` | open nodes this one transitively unblocks | 100 |
| `critical_path_depth` | the longest remaining chain from this node, counting itself | 10 |
| `out_degree` | nodes it directly unlocks in the reduced graph | 1 |

Each term is `{value, weight, points}` with `points = value * weight`; `score.total` is their sum
and equals `priority_score`.

### Finding codes

| Code | About |
| --- | --- |
| `issue.untrusted` | an issue that failed the trust gate; `detail` has id, url, state, author, reasons, referenced_by, and never a title |
| `pull_request.untrusted` | a pull request that closes a task but is not trusted (threat model C4) |
| `issue.unmodeled` | an open home issue with no frontmatter |
| `issue.opaque` | a referenced issue with no frontmatter: it blocks until it closes |
| `container.excluded` | a container, which is not a node |
| `parent.not_planned` | a blocker closed as not planned, which still satisfies the edge |
| `frontmatter.violation`, `frontmatter.warning` | one per rule an issue breaks or strains; `subject` is the issue |
| `edge.redundant` | an edge implied by a longer path, left out of the reduced graph |
| `edge.soft_or_low_confidence` | a `--verify-dag` edge below `--min-confidence` or soft |
| `prerequisite.unknown`, `prerequisite.stale_merged_hint` | why a plan is `unresolved` |
| `graph.cyclic_node` | a node on or behind a cycle |
| `relationship.only_in_frontmatter`, `relationship.only_in_github` | `--compare-relationships` drift |
| `since_last.no_previous` | `--since-last` found nothing to compare with |

A finding's `message` is built from ids, states, logins and the rule broken; the only issue text
it can carry is a trusted issue's frontmatter line in a `frontmatter.violation`.

A node line's `size_hours` is an integer or null. An issue whose `.size_hours` is not an integer is
a `frontmatter.violation` (the plan is not `ok`), and its line carries null; the plan's
`artifact_hash` is computed over the 1.x document, which keeps the value as written.

## Errors and exit status

| Code | When | `retryable` |
| --- | --- | --- |
| `gh.command_failed` | a `gh` call failed, a trust lookup included | true |
| `gh.list_limit_reached` | a list filled its limit and may be truncated | false |
| `gh.response_invalid` | a `gh` answer had the wrong shape (no `isDraft`, no edit-history connection, unparseable JSON), or an edit history repeated a cursor or ran past 1,000 pages | false |
| `gh.mutation_failed` | the `PATCH` of a child's body failed | true |
| `git.command_failed` | a `git` call failed (inventory, branches) | true |
| `root.invalid_reference` | never from the command line: there a `--root` that is not `owner/repo#N` is a startup failure (`startup.arguments_invalid`, exit 3, no `retryable`, no receipt). The code remains for discovery called without that check | false |
| `root.out_of_scope` | a `--root` outside the trusted scope | false |
| `edge.out_of_scope`, `edge.child_not_issue`, `edge.child_untrusted`, `edge.child_frontmatter_missing`, `edge.child_frontmatter_invalid`, `edge.rewrite_impossible` | an edit refused before any write | false |
| `edge.rollback_failed` | an added edge could not be removed after the run failed | true |
| `frontmatter.invalid` | an issue in the closure has invalid frontmatter | false |
| `issue.not_found` | Rust binary only: a reference resolves to nothing, for the cause the core recorded; `detail.rule` is `D11`, `D12` or `D13` | false |
| `bundle.capture_failed` | Rust binary only: `--capture-bundle` could not write the bundle or its record | false |
| `bundle.unreadable`, `bundle.invalid` | Rust binary only: the `--from-bundle` file cannot be read or is over 64 MiB, or is not an `issue-dag-observations/1` bundle (`detail.at`, `detail.problem`) | false |
| `bundle.incomplete` | Rust binary only: the bundle lacks a slot the run reads (bundle rule OB5); `detail.missing` is its path | false |
| `observation.unavailable` | Rust binary only: a replayed bundle records a slot the run needs as unavailable (OB4); `detail.unavailable` is the recorded reason | false |
| `evaluation.unreadable`, `evaluation.invalid`, `evaluation.unavailable`, `evaluation.differs` | Rust binary only: the `--from-record` file cannot be read, is not a `taskalisk-evaluation/1` record, does not retain a bundle this binary can plan, or plans to another result than it records | false |
| `plan.reads_disabled` | Rust binary only: `--offline` with no `--from-bundle` or `--from-record` | false |
| `graph.cycle`, `graph.unresolved_prerequisites` | the graph could not be ranked | false |
| `dag_spec.unreadable`, `dag_spec.invalid` | the `--verify-dag` file cannot be read or has the wrong shape | false |
| `uncaught.exception` | a defect: the traceback is in the receipt only, never on stderr | (writer) |

An error from a `gh` or `git` call carries `detail: {source, error, phase}`, where `phase` is
`edge_edit` (before or at the write), `discovery`, `relationships` or `inventory`.

| Status | Meaning |
| --- | --- |
| 0 | the command succeeded |
| 2 | it failed and reported one or more `parley.error` lines |
| 3 | a usage error before the run began, or a schema file of the declaration that cannot be read (`startup.declaration_unreadable`): one `parley.startup.failed` line on stderr, nothing on stdout, no receipt |
| 4 | an output or receipt sink failed |
| 1 | only when `scripts/parley_emit.py` is missing: Python cannot import the writer and prints its own error (see What is not guaranteed) |

1.x used 1 for "the graph or frontmatter is invalid" and 2 for "GitHub could not be read". Both are
now 2, because Parley reserves 2 for a reported error; the error code's namespace (`gh.`, `git.`
against the rest) and `retryable` carry the distinction instead. The old argparse usage error,
which printed text and exited 2, is now a startup failure, exit 3.

Arguments are validated before the bootstrap line, as Parley asks (spec 3.2; decided on
flyingrobots/parley#91 and #98): a flag that does not parse (an abbreviated flag such as `--from`
included: every flag must be spelled in full), flags that contradict each other (a mode flag
naming another command than the one given, such as `inventory --from-github`, included), a
`--root` or an edge that is not `owner/repo#N`, and a self-edge are startup failures, exit 3, with
no receipt, because a mistaken call did no work. Whatever needs GitHub to decide (a root outside
the scope, an untrusted child) is a command error with a receipt.

## Receipts, `inv` and `artifact_hash`

Each run writes `.parley/receipts/<run>.jsonl` under the working directory (the writer creates
`.parley/.gitignore` holding `*`). Retention is by count: past 50 receipts of this tool, the oldest
completed ones are deleted; other tools' receipts are never touched. A
receipt holds the redacted arguments, the resolved question, one step per decision (each
repository and trust lookup as it is read, with the reason), copies of every result and error,
and `end`.

It never holds an issue's body. It holds the titles of trusted issues, because it copies the
result lines that carry them (and, for `inventory`, every open issue's title; see Commands).
Discovery records what it read as one step,
`observed N issue(s)`, whose detail lists each issue by `id`, `state`, `state_reason` and the
SHA-256 of its title and body. Those bodies are the run's declared input `github:issues`
(role `observations`): its digest is over that list in canonical JSON, so `inv` (in
`receipt.inputs`, the writer's derivation) identifies the question and the issue text it was
answered from. PR states, branches and permission answers are live context outside that
boundary: two runs with one `inv` can still differ when only those moved. `verify` declares its
DAG file as the input; `inventory` declares the snapshot it read. A DAG file `verify` could not
read is recorded with `error: dag_spec.unreadable` and no digest, and `inv` is omitted; one that
was read but is not JSON is recorded by the bytes read.

`artifact_hash` on the plan line is the SHA-256 of the canonical result document (keys sorted,
compact separators, a trailing newline), computed exactly as 1.x computed `meta.artifact_hash`; the
Rust renderer's hash differs from it in the cases the next paragraph lists. `inv` names the question
and its inputs; `artifact_hash` names the answer. The same `inv` with a different `artifact_hash`
means live context outside the declared inputs changed.

**The Rust renderer's `artifact_hash` (a permanent exception).** The Rust binary hashes the artifact
it emits: the result document in the 1.x shape, built from its own lines, written as Python's
`json.dumps` writes it (every character outside U+0020 to U+007E escaped, astral characters as
surrogate pairs). The schema requires the field, so it is always present. It equals the Python's
hash only when that document holds no intended difference: no frontmatter finding (whose
message is prose the core writes as fixed text, one per rule), and a display input that supplies
the titles, URLs and branches (flyingrobots/taskalisk#31 fills it from the adapters). An untrusted
issue or pull request is no exception: the core keeps the trust gate's reasons, and the renderer
words them as the Python does (#46). Otherwise it is a different, equally
deterministic hash of a different document. Compare `artifact_hash` values from one implementation
only. The parity tests (`crates/taskalisk/tests/parity.rs`) assert equality where it holds and,
elsewhere, that the hash is 64 hexadecimal digits and the same on every run.

Where the specification records a difference from the Python
(`tests/fixtures/issue-dag/notes/python-differences.md`), the Rust binary follows the
specification, and the parity tests leave that corpus case and its `--python` twin out. For
example, a task that names the same not-planned prerequisite twice gives one `parent.not_planned`
finding in Rust and one per mention in 1.x (difference 10, a compatibility exception; corpus
`graph/g3-duplicate-not-planned-prerequisite`).

One difference is the renderer's own, not the specification's: when a run has both an unknown
prerequisite (X3) and a cycle (G4), the core reports every finding of both (F4, F5), but the 1.x
document, like the Python, which checks prerequisites before cycles, is `unresolved` with
`graph.unresolved_prerequisites` and names no cyclic node. Read the core's findings, not the
1.x document, for the cycle in such a run.

## `--since-last`

With `--since-last`, a plan compares its frontier with the most recent other completed receipt
of this tool in the same receipt directory whose `resolved.question` is the same (the `--repo`
relative to the working directory, the roots, and the trust flags) and whose plan compiled. It
reads only that receipt, never GitHub. Each difference is a `frontier_change`: `promoted`
(blocked before, frontier now), `added` (absent before, frontier now), `newly_blocked`, `closed`
(open before, closed now) or `left` (open before, now absent and not known to be closed). With
no such receipt, the plan line's `since_last.compared_with` is null and a `since_last.no_previous`
finding says so; that is not an error. A plan that did not compile (a cycle, an unresolved
prerequisite) has no frontier, so it is not compared: there is no `frontier_change` and no
`since_last` on its plan line, and a receipt step says why.

A receipt is a local file that anyone who can write the directory can plant, so a receipt is
compared with only when its file name is its run id, that run id is a ULID (26 Crockford base32
characters, which is what the writer mints), its `taskalisk.plan`, `frontier_node` and `node`
lines validate against the exact schemas they name, and every node id is an issue
(`owner/repo#N`). Any other is skipped with a receipt step, `--since-last: ignored receipt ...`,
and the next is tried; the step repeats the file name only when it is a ULID. This keeps a
planted file from putting an invalid line or free text on stdout: the only strings taken from a
receipt are ULID-shaped run ids (`since_last.compared_with`, `since_run`) and issue-shaped node
ids. It does not authenticate a well-formed receipt, so a `frontier_change` is advice about this
directory's history, never an instruction.

## `--human`, `--dry-run`, discovery

`--human` prints the plan summary, a ranked table of the frontier, the batch and every finding,
and errors as `error <code>: <problem> (<remedy>)`. Node, wave and edge lines are not printed;
the receipt is unchanged. Control characters, line separators and bidirectional overrides in any
GitHub text are printed as `\uXXXX`. `--emit-roadmap --human` prints the ROADMAP block as is.

`edit --dry-run` runs every check on the edit, writes nothing and recompiles nothing (the graph
it would compile is the one without the edit); `edge_edit.dry_run` is true and `changed` says
whether the body would change.

`--schema` emits one `parley.command` line per command and one `parley.schema` line per message
type; `<command> --help` emits that command and the schemas of its results and errors. Both exit 0.

## Secrets and paths

`GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN` and `GITHUB_ENTERPRISE_TOKEN`, every token
variable `gh help environment` names, are declared secrets: their values are
replaced by `[redacted]` in every line and in the receipt, and the receipt head names which were
set. A credential inside a URL in `gh` or `git` output is replaced by `[redacted]` before it is
recorded: userinfo (`scheme://user:secret@host`), and the value of a query or fragment parameter
named `token`, `access_token`, `key`, `secret`, `password`, `sig`, `signature`, `auth` or `code`,
in any case and any position. A value runs to the next `&`, `#` or white space, past any `;`
inside it, so a parameter that follows a `;` in the same value is redacted with it. Other
parameters, and the quotes, brackets or full stop around a URL, are kept. The names are a
heuristic: a secret in a parameter not on that list, under a percent-encoded name, or outside a
URL, is not found; nor is a URL whose scheme is longer than 32 characters, a bound that keeps the
scan linear. Closing punctuation (`. , : ! ? ' " ) > ]`) at the very end of a value is shown, as
the text around the URL. The home directory is shown as `~` in worktree paths and command
output, as in 1.x. The bootstrap line's receipt path is absolute because the protocol requires
it.

## What is not guaranteed

- The compile holds the closure in memory, because ranking needs the whole graph; the output is
  written one line per record and never assembled into one document. A thousand-node backlog
  compiles and streams in under 60 seconds in the suite, with no line over 65,536 bytes. In GitHub mode the
  time is the `gh` calls (one edit-history query per trusted issue): measured once on 2026-11-22, a
  999-issue backlog against `tests/fake_gh.py` took 77.7 seconds and wrote 3,992 stdout lines, the
  longest 26,842 bytes; that run is not part of the suite.
- A `--emit-roadmap` text, or a receipt step listing a large closure, can exceed 65,536 bytes;
  the writer then stores it beside the receipt as a sidecar.
- A hard crash of the interpreter or a signal can leave the streams without `end` (Parley §6).
- If `scripts/parley_emit.py` is missing from an installed skill, the import fails before any
  Taskalisk code runs: Python prints a `ModuleNotFoundError` traceback on stderr and exits 1. This
  is the one plain-text error and the one status outside 0, 2, 3 and 4. A missing or damaged schema
  file, by contrast, is a startup failure (exit 3): `taskalisk.py` builds that one line itself,
  under the writer's `parley.startup.failed` schema and checked by the writer's validator, because
  the writer needs the declaration to start.
- `gh` is run with its output captured, so nothing it prints reaches the streams directly; its
  stderr text reaches a line only inside an error's `detail`, after the sanitising above.

## The Rust binary

`crates/taskalisk` builds a binary, `taskalisk`, whose `plan` command writes this contract
(flyingrobots/taskalisk#31). It is named as the tool is named: the receipts of both
implementations say `tool: taskalisk`, because they are one tool under one contract and the binary
replaces the script at the cutover (#32); `v` is the crate's version, so a receipt says which one
ran. The envelope is a port of the vendored writer's, not a call to it, and keeps its rules:
the bootstrap line, one sequence across the streams and the receipt, the receipt under
`.parley/receipts/` of the working directory, `inv` over the declared input `github:issues`, the
`gh` token variables redacted, sidecars past 65,536 bytes, retention of 50 receipts, `--human`.
Every line is written with its keys in sorted order, the envelope's included.

It differs from the Python in these ways, each tested in `crates/taskalisk/tests/cli.rs`:

- **Commands and flags.** Only `plan`. `--repo`, `--root`, `--sem-capacity`, `--trust`,
  `--trust-owner`, `--trust-repo`, `--trust-codeowners`, `--from-github`, `--human` and `--help`
  are accepted, with the binary's own `--capture-bundle`, `--from-bundle`, `--from-record` and
  `--offline` (see *Capture and replay*); every other flag and command is
  `startup.arguments_invalid`, exit 3, never ignored. A flag's value may follow `=`. `--help` describes `plan` with the schemas of the lines
  it writes and of `parley.error` and `parley.startup.failed` (copies of the writer's, held equal
  by `tests/test_binary_schemas.py`).
- **Frontmatter messages.** A frontmatter finding's message is the core's fixed text (see
  `artifact_hash` above). Every line validates against its schema; an `issue.untrusted` or
  `pull_request.untrusted` finding carries the trust gate's reasons and message as the Python
  words them (#46).
- **The receipt.** The steps are fewer: the home repository, the branches, the pull requests,
  `observed N issue(s)`, the evaluation record and retention, and no step per trust decision. In
  the observed list a body that was not read (an untrusted author's, a pull request's) has a null
  `body_sha256`, so `inv` differs from the Python's for the same backlog.
- **The evaluation record.** Every plan the core answers (a plan, an invalid graph, an incomplete
  read, a rejected root) records its `taskalisk-evaluation/1` record, from
  `issue-dag-bundle::unretained`, as the receipt step `recorded the evaluation
  (taskalisk-evaluation/1)`, in `detail.record`. Without `--capture-bundle` the observation bundle
  is not retained, so the record's `observations` and `not_observed` are unavailable and its
  replay is unavailable. The record holds no issue body or title. With `--capture-bundle` the
  retained record is written beside the receipt instead (it holds the bundle, and so issue
  bodies, which a receipt never does), and the receipt step `captured the observation bundle and
  its evaluation record` names both files.
- **Capture and replay** (flyingrobots/taskalisk#59). The Python has no equivalent.
  - `--capture-bundle` (off by default) writes, into the run's own directory beside its receipt,
    `.parley/receipts/<run>/bundle.json`, the `issue-dag-observations/1` bundle of every slot the
    `gh` adapter read, and `.parley/receipts/<run>/evaluation.json`, the run's
    `taskalisk-evaluation/1` record made by `issue-dag-bundle::evaluate`, which retains that
    bundle. They are where sidecars go: under `.parley/.gitignore` (`*`), created new
    (`O_EXCL`), and deleted with their receipt by retention. They hold every read issue's body
    and the trust observations (authors, associations, permissions, pull requests); a bundle
    holds no title, URL, label or branch (bundle rule OB12). Every declared secret's value is
    redacted from both before they are written, and the step lists the JSON Pointers redacted; a
    value the redaction cannot reach (an object key) refuses the capture,
    `bundle.capture_failed`. The step records each file's path relative to
    `.parley/receipts/`, its SHA-256 and its size.
  - `--from-bundle FILE` plans from a bundle, and `--from-record FILE` from an evaluation
    record, which it first replays through `issue-dag-bundle::replay` (decision D14): the record
    must retain its bundle and plan to the result it records, or the run is
    `evaluation.unavailable` or `evaluation.differs`, exit 2, with no plan. Either reads no `gh`
    and no `git`: the bundle answers through a recorded forge, `effects.network` is false, and
    the file is the declared input (role `observations`), so `inv` covers it. The flags a
    bundle answers (`--repo`, `--root`, `--sem-capacity`, the trust flags, `--from-github`,
    `--capture-bundle`) are refused with them, exit 3. A slot the bundle does not hold is
    `bundle.incomplete` (OB5), and one it records as unavailable `observation.unavailable` (or
    `issue.not_found` when it records a cause), exit 2: never read as empty. A file larger than
    64 MiB (67,108,864 bytes) is refused unread, `bundle.unreadable` or `evaluation.unreadable`
    with `detail.limit`, rather than read whole into memory; a thousand-issue bundle is a few
    megabytes. The plan's decisions
    are the captured run's; its display is not, because a bundle records none: each issue's
    title is `(title not recorded in the bundle)`, its URL null and its recoverable branches
    empty, so `artifact_hash` differs from the live run's.
  - `--offline` disables the `gh` and `git` reads. With `--from-bundle` or `--from-record` it
    changes nothing; without them the run is `plan.reads_disabled`, exit 2.
  - `tests/fixtures/bundles/flyingrobots-taskalisk.bundle.json` is a bundle of this repository
    captured this way, read-only, with the result it planned to beside it; the suite replans
    from it offline.
- **Refused where the Python relocates.** The binary has no state-directory fallback; each case is
  a startup failure, exit 3, with no receipt. A `.parley` that cannot be written is
  `startup.receipt_unwritable`. A receipt path that would carry a declared secret's value (the
  working directory's path holds it) is `startup.secret_in_path`. A `.parley/.gitignore` that
  would let `git add` stage a receipt is `startup.receipt_stageable`: one with no line `*`, or a
  line the writer's rule cannot rule out, a negation that can match `receipts` or a line holding
  a NUL byte (the Python writer's `_negation_reaches_receipts`, ported rule for rule, so
  `!.gitignore` is accepted). The file is the user's and is left alone; the binary creates it,
  holding `*`, only when it is absent, written to a temporary name and linked into place so a
  concurrent first run never reads it empty. A run id that carries a declared secret is drawn
  again up to 16 times, then the run is `startup.secret_in_path`.
- **Redaction.** A declared secret's value is replaced by `[redacted]` in every string of every
  line, `resolved` included: the head records the argument indexes, the JSON Pointers into
  `resolved` and the variable names in `redacted`, and `inv` is computed over the redacted
  `resolved`, as the Python writer does. A secret inside an object key is not redacted.
- **A reference that resolves to nothing.** When the core records why a read found nothing
  (bundle rule OB17), the run's `parley.error` is `issue.not_found`, with `detail.rule` the
  profile rule (`D11` no such owner, `D12` no such repository, `D13` no such number),
  `detail.not_found` the cause (`owner`, `repository` or `number`) and `detail.reference` the
  reference read, when the reason names one; exit 2. The core's catalogued codes (`profile.D11`
  and the rest) are not used as error codes, because a `parley.error` code is lower case. Without
  a recorded cause it is `gh.response_invalid`.
- **Symlinks are followed**, as the Python writer follows them: `.parley`, `receipts/` and `--repo`
  may be links. Every file the binary writes is created new (`O_EXCL`), so it never overwrites a
  file a link points at.
- **Not ported from the writer.** The capture of stray output, `--dry-run` and `--schema`.

## Conformance

The Parley doctor cannot run in this repository's CI. It was run locally on captured real runs
committed under `tests/fixtures/doctor/` (plan, inventory, edit, an edit that made a cycle, a `gh`
failure, verify, `--help`, `--schema`, and the receipt of a `--human` run), and on live plans of
flyingrobots/taskalisk and flyingrobots/parley; each verdict was `CONFORMS 0 violation(s)`. The
doctor validates the `parley.*` lines against the protocol and reports the `taskalisk.*` lines as
partial, because it does not hold the tool's schemas; those lines are checked by the suite, which
re-validates every committed line offline against the exact schema it names, with the writer's
bounded checker. `tests/capture_doctor_runs.py` recaptures them.
