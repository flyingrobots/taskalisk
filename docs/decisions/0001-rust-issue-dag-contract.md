# 0001. Rebuild Taskalisk in Rust around a versioned issue-dag contract

Status: Accepted by James Ross on 2026-11-11 in a working session, and
recorded by the merge of this record, except where a decision is marked
**Proposed**.

Each decision carries one of two marks:

- **Decided**: James Ross accepted it on 2026-11-10 or 2026-11-11.
- **Proposed**: recommended and not yet accepted.

The analysis behind this record is the working paper *Issue Graphs as Typed,
Versioned Documents*, revision 4 of 2026-11-11, which is not published. Two
independent reviews of earlier revisions shaped it. This record states the
decisions; the paper gives the arguments.

## Context

- Taskalisk is one Python script, `skills/taskalisk/scripts/taskalisk.py`,
  with 89 offline tests at `4949d4e`.
- Issue #22 added lint, typing, coverage and structure gates to that Python.
  It blocked #1 and #3, and through them the executor chain. Its branch held
  324 passing tests and a failing coverage gate.
- The executor is the larger part of the planned code. None of it exists.
- On 2026-11-10, listing every issue of flyingrobots/taskalisk,
  flyingrobots/geordi, flyingrobots/echo, flyingrobots/bunny and
  git-stunts/git-warp (at most 600 per repository; git-warp reached that
  limit) found 237 that carry `issue-dag/2` frontmatter. Their references
  reach 13 repositories under 3 owners. Repositories outside those five were
  not counted.
- A manual audit on 2026-11-10 found two worktrees that belonged to merged
  pull requests, and two merged pull requests (#16, #17) with no issue.
  Nothing in the tool reports either condition.
- An edge edit replaces the whole issue body and can overwrite a concurrent
  edit. Issue #1 specifies the repair.

## Decisions

### 1. Four lifecycle rules, enforced by detection — Decided

1. All work is represented by an issue.
2. Work in progress has a draft pull request.
3. A closed issue means the work was completed with accepted evidence, or
   abandoned.
4. Worktrees and branches are removed after the issue closes and the work is
   pushed or merged.

Taskalisk reports violations. It never deletes a worktree, closes an issue or
opens a pull request. Cleanup is done by whoever merges. A new `audit`
command checks the rules; `plan` withholds a task from dispatch only when its
work has branch commits and no open pull request. Cleanup findings never block
dispatch (#33).

### 2. Rust, with a hexagonal architecture — Decided

Taskalisk is rewritten in Rust. A core crate holds the domain and the ports
and performs no I/O; it plans over a recorded set of observations. An adapter
crate holds the `gh` and `git` adapters, an in-memory forge for tests, the
renderers and the command line. Ports: `Forge` and `LocalRepository`; later
`AgentLauncher` and `Locks`.

Each forge write is a named port operation. A narrow operation does not
narrow its effect: the edge edit still replaces the issue body, and its
concurrency contract is the one in #1. Nothing restores a body after a write.

### 3. Repositories — Decided

| Repository | Holds |
| --- | --- |
| `issue-dag` | The specification: formats, planning profiles, the version table, the conformance corpus |
| `issue-dag-py` | The Python compiler, as the source of characterisation cases |
| `taskalisk` | The tool |

The Rust parser starts as a crate in the Taskalisk workspace and moves to
`issue-dag-rust` when the format stops moving or a second consumer appears.

### 4. Edges stay on the dependent — Decided

`.blocked_by` remains the only edge field. A task's direct prerequisites are
then a function of its own document, which is what keeps other authors from
adding or removing them. Containers and `.children` stay.

### 5. Three identities and an evaluation record — Decided

- A **typepack** is a named, versioned shape with its laws and a link to its
  predecessor.
- A **format** is a typepack plus a carrier grammar and a key binding.
  `issue-dag/2` is a format.
- A **planning profile** holds the graph rules: edge satisfaction, resource
  scope, deferral, completion policy, ranking, batches, and the consequence of
  each lifecycle finding.
- Every plan emits an **evaluation record** naming the formats, profile and
  evaluator it used and the observations it planned from. A plan is replayable
  only when the record retains the complete planner input.

### 6. Versions and compatibility — Decided

- A document is judged under its declared version. A reader accepts every
  version that is not retired. A version is retired only when its documents
  can be misread.
- A compatibility claim names the observables it preserves: local acceptance,
  decoded meaning, structure, readiness, ranking or batch. Its verdict is
  compatible, incompatible or unknown. A passing corpus supports a claim and
  never proves it.
- Every reader in normal planning use for a repository accepts a version
  before any document there declares it. A recovery reader is kept that reads
  every input of its own repair plan.

### 7. Policies for the `/3` profile — Decided

1. **Parking.** When parking leaves branch commits, the draft pull request
   stays open and the reason is recorded in `.deferred`. Closing a pull request
   unmerged ends that attempt, not the issue's goal.
2. **Holds.** `.deferred` or `.status: blocked` holds a task from new dispatch
   even when it has an open pull request. What a running worker does is
   executor policy.
3. **Completion by `.type`.** Code-delivery types need a merged, trusted
   closing pull request. Decision, research, investigation and spike issues
   may instead close with a trusted comment that links a durable record.

Further profile changes, each shipped separately with a `compare-plans`
report (#34):

- An edge is satisfied only when its blocker closed as completed (#36).
- Resource keys are scoped to their repository; `host/` keys are
  machine-wide (#37).
- **Proposed:** an edge is satisfied only when its blocker also meets its
  completion policy.

The container rule is not a `/3` change. `docs/frontmatter-model.md` already
says, for `issue-dag/2`, that a container must not have `.blocked_by`. The
Python accepts `.blocked_by: []` on a container because it tests whether the
list is empty rather than whether the key is present. The rule stands as
written; #26 classifies the Python's behaviour as a defect.

### 8. Order of work — Decided

1. Write the `/2` specification and profile (#25).
2. Reconcile the Python against it and freeze the corpus (#26).
3. Port the core to Rust at `/2` parity (#27 to #30). `--explain` (#4) is
   built on the core after #30.
4. Add the adapters, safe edge writes and the cutover (#31, #1, #32).
5. Add the lifecycle audit and `compare-plans` (#33, #34).
6. Land the `/3` changes one at a time (#35 to #37).
7. Build the executor in Rust (#3, #9 to #15).

The format and the implementation language never change in the same step.

## Alternatives rejected

| Alternative | Reason |
| --- | --- |
| Finish the Python gates (#22) first | Gates on code about to be replaced; the reconciliation step does not need them |
| Out-edges as a second source (`.blocks`) | Two copies of one edge, and any author could block another author's task |
| Out-edges as a verified hint | Every edge edit touches two issues; a missing hint is silent |
| Remove containers | They are how members in other repositories are found |
| Generate the parser from Wesley | Generated types are a raw serialisation form; the parser must parse, validate and only then admit a typed record |
| Promise that an edge edit preserves concurrent edits | GitHub documents no conditional update for issues |

## Consequences

- #22 and its pull request #23 closed unmerged. The branch, with checkpoint
  `97b6987`, is kept as characterisation evidence.
- Draft pull requests #19 and #21 do not merge; #1 and #3 are re-scoped to
  Rust and the pull requests close at the cutover (#32).
- No new feature lands in the Python compiler.
- Users build a binary from source until release binaries exist.
- `/2` documents need no edit to remain valid.

## Open questions

- What counts as a durable record for completion without a merge, and who may
  accept it.
- Which pull request decides a task's state when an issue has several.
- What seeds discovery of downstream work (threat-model control C15).
- How the binary is distributed.
- Whether the corpus digest sits inside or beside a format's identity.
