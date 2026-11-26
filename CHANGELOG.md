# Changelog

The Taskalisk skill's releases. The skill version (the release tag, and `__version__` in
`skills/taskalisk/scripts/taskalisk.py`) moves when the code changes; each output message schema
under `skills/taskalisk/schemas/` has its own version and moves only when that message changes. A
schema version under `Unreleased` is a draft and may change in place.

## Unreleased

### Added

- **The Rust document core** (flyingrobots/taskalisk#27). A Cargo workspace at the repository root
  (Rust 1.100.0, pinned in `rust-toolchain.toml`) holds `crates/issue-dag-core`, a library with no
  I/O and no dependencies: a hand-written `issue-dag/2` carrier parser and validator, the typed
  record a valid document decodes to, and the `.blocked_by` rewrite of edge-edit rule E4, which
  changes that one line and keeps every other byte, CRLF line ends included. All 165 document cases
  of the vendored corpus pass; for each `--python` twin the crate matches the normative case.
  Pending their specification text: a key repeated under C7 is present but judged by no other rule,
  while the rest of the document is judged; a repeated `.dag` leaves the version unknown, so C7 is
  the document's only violation, as C4 and P3 stop judging; an invalid document reports no warnings.
  CI runs the job "Rust workspace": `cargo fmt`, `clippy -D warnings` and `cargo test`, all locked.

- **The Rust graph core** (flyingrobots/taskalisk#28). `issue-dag-core` now plans over recorded
  observations, still with no I/O: the run parameters and observation slots as domain values, the
  `Forge` and `LocalRepository` ports with a `RecordedForge` that answers from them, the admission
  policy `taskalisk/threat-model` (AD1 to AD10, CODEOWNERS parsed as AD7 states), and `plan`:
  rejection (I2, the policy name included), discovery and closure (D1 to D10), opaque, untrusted
  and unmodeled issues, the cross-document rules (X1 to X3), the graph (G1 to G5), status (S1,
  S2), readiness (Q1, Q2) and the outcome classes (F1 to F5) with findings labelled as F5 states.
  An unavailable observation makes the run incomplete, never empty; a slot that was never recorded
  is an error, not an outcome. A run's findings are the crate's one `Finding` type (#43's), which
  gains `concerns`, the reference a D3, D5, X2 or X3 finding is about; the rules of a run have
  stable codes in the same table (`profile.D3`, `profile.D4`, `profile.D5`, `profile.X2`,
  `profile.X3`, `profile.G4`, declared with `Rule` and `PROFILE_RULES`), all errors. Admission,
  input and outcome rules give no finding: they make a run incomplete or rejected. A new crate,
  `issue-dag-bundle`, reads an
  `issue-dag-observations/1` bundle into the core and rejects one that breaks OB1 to OB13, or that
  gives a JSON member twice. Cycles (G4) use Kahn's algorithm and the reduction (G5) descendant
  bit sets, so a 5,000-task chain or wide graph plans in under a second. All 179
  graph cases of the vendored corpus pass; for each `--python` twin the crate matches the
  normative case. Ranking and batch selection came next (flyingrobots/taskalisk#29, below).
  Choices the specification leaves open: an admitted pull request's draft flag is read only where
  S2 needs it, for an open node of the home repository the pull request closes (I5); an invalid
  run reports its graph unless a prerequisite is unknown (X3) or the edges form a cycle (G4); a
  bot's `app/` prefix and `[bot]` suffix are matched without regard to case; a bundle with an
  `observations` member the bundle rules do not define is rejected. A key repeated in an invalid
  document contributes nothing to its reading, as format rule C7 now rules
  (flyingrobots/taskalisk#104).

- **The gh adapter** (flyingrobots/taskalisk#56). A new crate, `crates/issue-dag-gh`, implements
  the core's `Forge` port by running `gh` (an argument vector, never a shell string; `gh` on `PATH`
  unless another program is configured). It makes the Python compiler's reads with its limits: the
  REST issue list (`--paginate`, 1,000 issues) and issue, the body edit history in GraphQL (a page
  that claims another without a cursor, a repeated cursor, or more than 1,000 pages is refused),
  `gh pr list` with closing references (`--limit 500`), the collaborator permission and the first
  CODEOWNERS file. It fails closed: a failed read, an answer in the wrong shape, or a list that
  fills its limit is a `GhError` with the Python's code (`gh.command_failed`,
  `gh.response_invalid`, `gh.list_limit_reached`), and its slot is answered unavailable, so the run
  is incomplete and exits 2, never planned from an empty answer. HTTP 404 means "none" only for a
  permission (not a collaborator) and a CODEOWNERS path; an issue that answers 404 is unavailable
  (D10). Each slot is read once, and what was read replays through `RecordedForge`. As in the
  Python, the body's edit history is read only after the author is trusted, so an issue a stranger
  wrote costs no further query (threat model C15): the `Forge` port gains `body(reference)`, which
  the planner calls only after admission, and an issue of the home listing is filled from the
  listing, never fetched again; `Issue` has no body, and `Observations` keeps the bodies
  read in their own map, `bodies`. The bundle format is unchanged: the loader reads an issue
  slot's nested `body` into that map, a bundle may leave out a body the run never reads (OB14),
  and a run that reads one not recorded finds it missing (OB5). An issue listed on two pages makes the listing unavailable
  (OB6), and an edit-history page without a boolean `hasNextPage` is refused. `gh` runs without
  `GH_FORCE_TTY`, `CLICOLOR_FORCE`, `GH_DEBUG` and `DEBUG`, and with `GH_PROMPT_DISABLED=1`,
  `NO_COLOR=1`, `GH_NO_UPDATE_NOTIFIER=1` and `GH_PAGER=cat`, which no configured variable
  overrides; text the server returns is left out of an error's reason. Unlike the Python, a pull
  request's head repository is not observed.

- **The git adapter** (flyingrobots/taskalisk#57). A new crate, `issue-dag-git`, implements the
  core's `LocalRepository` port by running `git` with argument lists, never a shell:
  `for-each-ref` with NUL-separated fields for local and remote-tracking branches (tip and
  subject, a subject that is not UTF-8 read leniently; `origin/HEAD` and other symbolic refs left
  out), `worktree list --porcelain -z` for
  worktrees (path, head, branch or detached or bare, locked, prunable, whether the directory
  exists), `status --porcelain -z` in each worktree for its dirty state, and `rev-list
  --left-right --count --end-of-options` for ahead/behind (an empty revision or base, or one
  holding `..`, is refused as `InvalidRevision` instead of being read as `HEAD` or a range). The
  port gains `branches`, `worktrees` and `ahead_behind`, with the value types `Branch`,
  `BranchScope`, `Worktree`, `Checkout` and `AheadBehind`, because the inventory reports them and
  the port held only local branch names.
  `GitRepository::open` takes the top level of a work tree (main or linked) and records its git
  directory and work tree (`rev-parse --absolute-git-dir --show-toplevel`); a subdirectory, a
  `.git` directory and a bare repository are refused. Every read runs against the recorded
  `--git-dir` and `--work-tree` and never discovers again, so a repository whose `.git` is gone
  fails instead of reading the repository above it; each worktree's `status` names that
  worktree's own `.git` the same way, after checking that it belongs to the opened repository (a
  worktree directory replaced by another repository fails as `ForeignWorktree`, and a linked
  worktree whose `.git` is another worktree's, as after two directories are swapped, fails as
  `MisplacedWorktree`; a locked worktree whose directory holds no `.git`, such as an unmounted
  volume, has `dirty` unknown); a submodule's or
  `--separate-git-dir` repository's main worktree, which git lists at its git directory, is read
  through the recorded work tree. It fails closed: each `read_*` method returns a `GitError`
  when `git` fails or answers in a shape it cannot read (an empty worktree listing included), for
  a caller that needs the kind of failure, and the port answers `Unavailable` with the error's
  text, never an empty list. It only reads: every call passes `--no-optional-locks` and turns off
  `core.fsmonitor` and `core.untrackedCache`, so `status` neither rewrites the index nor runs a
  configured monitor command (a clean filter the user configured can still run, with the trust of
  the user's own `git status`), and removes every inherited `GIT_*` variable (`GIT_DIR`,
  `GIT_CONFIG_*`, `GIT_CEILING_DIRECTORIES`, `GIT_NO_REPLACE_OBJECTS` and the rest), so a run
  inside a hook reads the repository it was given. A missing worktree directory is reported
  (`path_exists` false, `dirty` unknown), not dropped.

- **Ranking and batch selection in the Rust core** (flyingrobots/taskalisk#29). `issue-dag-core`
  gains `rank`, which scores every open node of a reported graph (K1 to K5: in-flight and parked
  terms from the S2 status, a trusted linked pull request included; descendants by bit set; depth;
  out-degree in the reduced graph), orders them with identifiers compared as text (K6), and gives
  the waves (K7) and the critical path through reduced predecessors (K8); and `select`, which
  builds the batch from the dispatchable ready set in rank order (B1 to B5). Keys are subtrees in
  one key space, looked up in an ordered index of held subtrees instead of a pairwise scan; a
  semaphore without a capacity counts as 1 and is reported for every node B5 considers, including
  one skipped for a key conflict. One decision function returns either admission or the skip
  reason (`holds conflict`, or `semaphore full` with the semaphores over capacity), so every
  reason comes from the predicate that made the decision. The corpus test now compares every
  member of CC6, the ready set in rank order: all 179 graph cases pass. A 5,000-node chain, fan or
  wide frontier ranks and selects in well under a second in a debug build. Choices the
  specification leaves open: a graph whose edges form a cycle has no ranking at all (a run never
  reports one); the critical path is empty when no node is open; `unknown_capacity` and each
  skip's semaphores are in ascending order.

- **Evaluation records and offline replay** (flyingrobots/taskalisk#30). `issue-dag-bundle` gains
  the evaluation record `taskalisk-evaluation/1`: the observation bundle a run planned from, held
  whole in an observation slot, the evaluator's name and version, and the result in the corpus's
  CC6 form, with the formats, the profile, the discovery scope (home, roots, read scope, trust
  policy) and the facts not observed (every unavailable slot, by its path in the bundle) beside
  them. A record is compact JSON with its members in ascending order. `evaluate` plans a bundle and
  records it; `unretained` records a run that kept no bundle, the hook for the binary's live `plan`
  (#31). `replay` takes no forge, so it plans only through `RecordedForge` over the retained bundle,
  and reports the result reproduced or differing, byte for byte, with the recorded and the replaying
  evaluator, so a difference shows whether the evaluator changed; when the bundle is not retained,
  is not a bundle, lacks a slot the run reads, or names a format or profile this evaluator does not
  implement, it reports replay unavailable and plans nothing. A record that contradicts its own
  bundle is refused. Every graph case of the corpus replays from its record to the same bytes. The
  CC6 projection moved from the corpus test into the crate (`outcome_json`), and that test uses it.

- **Repeated keys, warnings and refusal order in the specification** (flyingrobots/taskalisk#104).
  The vendored issue-dag specification now states the rulings the Rust core implements: no rule of
  sections 3 to 5 labels a repeated key, so labels never depend on line order, while its lines keep
  their C6 and C8 labels; a repeated `.dag` gives C7 as the document's only violation; V10 warns
  only on a document with no violation, X1 included; edge-edit rule E3a refuses an invalid document,
  then a non-task, then a self edge; CC5 sorts labels by their UTF-8 bytes and lets an invalid
  result hold `"warnings": []`. The corpus gains 17 normative cases and 12 `--python` twins
  (differences 4, 19, 20, 21 and 22), digest `sha256:7204de0f…`.

- **Profile and bundle gaps in the specification** (flyingrobots/taskalisk#110). The vendored
  issue-dag specification (flyingrobots/issue-dag#7) now states the rulings the Rust graph core
  follows: a pull request's draft flag is required only when S2 reads it (I4, I5); a key repeated
  under C7 contributes no reference to discovery (D8); the bot prefix `app/` and suffix `[bot]`
  match without regard to case (AD3, AD4); a bundle with a repeated JSON member or an unknown
  `observations` member is not a bundle (OB1, new OB15); `unknown_capacity` and `semaphores` are
  in ascending byte order (CC6). The corpus gains 8 normative graph cases and 2 `--python` twins
  (differences 23 and 24, both defects of the Python), digest `sha256:aed5aeaa…`. The Rust core
  passed every new case unchanged; `issue-dag-bundle` gains a test for OB15. The title of each
  `--python` twin is now its disagreement note, what the compiler does, rather than the normative
  claim it disagrees with.

- **Document findings with stable codes** (flyingrobots/taskalisk#43). `issue-dag-core`
  judges a body with its issue's address, so rule X1 always applies, and returns findings: a stable
  code, a severity (error, or warning for the V10 advisory), the address as subject, and a message.
  A code is the rule's V12 label prefixed by the specification that states it: `format.C4` to
  `format.V10`, `version.P3` and `profile.X1`, tabled on `code` in the crate docs.
  Findings sort by subject, then code text. A message is fixed text that names keys and rules only,
  never a value or a line of the body; a body without a document has no findings.

- **Body warnings for a task** (flyingrobots/taskalisk#48). `issue-dag-core`'s `body_warnings`
  checks a valid task document's body against Taskalisk's writing convention
  (`skills/taskalisk/WRITING-TASKS.md`), not the format, so its codes carry the prefix `taskalisk.`:
  `taskalisk.outcome-missing`, `taskalisk.scope-missing` and `taskalisk.acceptance-missing` for a
  missing level-2 heading, matched exactly and case-sensitively outside code blocks and comments;
  `taskalisk.outcome-sentences` and `taskalisk.outcome-items` for an Outcome of more than one
  sentence or list item; `taskalisk.title-joins` for a title that joins two things with "and" or a
  semicolon. The title is an optional input, since the observation bundle records none; without
  it that check is skipped. Each is a warning with fixed text, tabled with the document codes and
  sorted the same way; a body filled minimally from each canonical template has none. A missing
  section's message names the exact heading it requires. `CODES` is the one public catalogue of
  every finding code with its severity, document codes, then profile codes, then body warnings;
  every family of findings registers there. The body is read as CommonMark renders it, parsed by
  `pulldown-cmark` (no default features, no extensions): headings may be ATX or setext, and
  code spans, code blocks and HTML, and real paragraph boundaries, are the parser's.
  `issue-dag-core` thus gains its first dependency: it still does no I/O, and depends only on
  `pulldown-cmark`, which supersedes "no dependencies" in the #27 entry above.

- **A provenance check for the vendored Parley writer** (flyingrobots/taskalisk#77).
  `scripts/check_vendored_writer.py` fetches the writer from flyingrobots/parley at the pinned
  commit and requires it to equal the pin and the copy; CI runs it. The offline pin test proves
  only that copy and pin agree, and the output reference now says which check proves what.

### Changed

- **One crate per port adapter** (flyingrobots/taskalisk#57). Decision 0001, section 2, is amended:
  the git adapter is `issue-dag-git` (#57); the `gh` adapter is to be its own crate, `issue-dag-gh`
  (#56); the renderers and the command line go in the binary crate (#31); the in-memory
  `RecordedForge` is in the core. Section 8, item 4, now names the issue of each adapter (#56,
  #57) and of the command line and renderers (#31, #58).

### Fixed

- **The gh adapter's tests no longer fail on Linux with "Text file busy"** (flyingrobots/taskalisk#122).
  Each forge test wrote its fake `gh` as a new executable file while other test threads spawned
  processes. Linux refuses to run a file that any process holds open for writing, and a child
  forked by another thread held it, so about 1 run in 25 failed (8 of 200 in
  `rust:1.100.0-bookworm`). The fake `gh` is now a symlink to `tests/fake_gh.py`, which is
  executable in git, so no test writes an executable. 200 runs: 0 failures.

- **Review findings on the Rust graph core** (flyingrobots/taskalisk#105, merged before its review
  finished). Each fix has a test that failed before it. The planner no longer stops at the first
  lookup it cannot make. It reads every slot the rules reach, so neither the order of the roots
  nor the order of discovery changes the result (D2), and a slot that was never recorded is never
  hidden behind an unavailable one (OB5). That holds for roots, for discovered prerequisites, for
  pull-request admission and for the editors of one body (AD8). When several lookups fail, a
  missing one is reported before an unavailable one, and the least of its kind is chosen. A
  transferred seed from the home listing that no document names gets no D5 finding: only a root
  keeps the finding itself (F5). `Admission::trusted` checks the read scope before the allowlist,
  so an allowlisted login is never trusted outside it (AD2). `Finding` compares, sorts and hashes
  by subject, code and concerned reference alone, so its message and severity are not part of its
  identity (F5). The bundle reader rejects a scope owner that is not a name of rule L1, such as one
  with a space or a non-ASCII letter. The planner parses each body once, and skips the reduction's
  n² descendant sets when no node has two children; test-only counters pin both. The 1 s bounds
  on large graphs, for planning and for ranking and selection (#29), left the default suite,
  which they made flaky under load, for an ignored `perf_` suite that the new CI job "Rust
  planning bounds (release)" runs.

- **The threat model no longer calls a failed trust check "untrusted"** (flyingrobots/taskalisk#101).
  Control C1 said a check that cannot be made is untrusted, and also that any trust lookup that
  cannot run exits 2. The second governs, as the compiler already does: a failed check fails the
  run and is never read as untrusted or trusted. The issue-dag admission policy (rule AD10) states
  the same. No behaviour changes.

- **An abbreviated or contradicting mode flag is a usage error** (flyingrobots/taskalisk#73).
  Every flag must be spelled in full: a prefix such as `--from` or `--verify` used to run
  `inventory` and exit 0. Under an explicit command, a mode flag naming another command
  (`inventory --from-github`, `verify … --from-github`) is refused. Both are startup failures,
  exit 3. Every documented spelling selects the same command as before. Compatibility: a call
  that relied on an undocumented abbreviation (`--min-conf`, `--from`) must spell the flag out.

- **A ROADMAP cell keeps a hostile title inert** (flyingrobots/taskalisk#75). The backslash is
  escaped first, every Unicode line break (CR, NEL, U+2028 and the rest) becomes a space, every
  other C0 or C1 control character (ESC included) and every bidirectional control is dropped, and
  a bare URL, a `www.` address, an email address or a mention gets a zero-width space so it does
  not link, whatever precedes it; a character reference such as `&#64;` stays text. A resource
  key is shown as written in its code span, no longer with doubled backslashes or `\[` escapes.
  A title that needs none of this renders byte-for-byte as before.

- **A repeated edit-history cursor ends the run** (flyingrobots/taskalisk#76). Reading an
  issue's body edit history, a page that repeats an earlier cursor, or a history past 1,000 pages
  of 100 edits, is `gh.response_invalid` (exit 2) instead of a loop without end.

- **A secret in a URL query string or fragment is redacted** (flyingrobots/taskalisk#78). The
  value of a query or fragment parameter named `token`, `access_token`, `key`, `secret`,
  `password`, `sig`, `signature`, `auth` or `code`, in any case, is replaced by `[redacted]` in
  `gh` and `git` text before it reaches a line or the receipt, as `user:secret@` already was.
  Other parameters, and the quotes, brackets or full stop around a URL, are kept.

- **A bad edge object in a `--verify-dag` spec is `dag_spec.invalid`** (flyingrobots/taskalisk#74).
  A `confidence` that is not a finite number (a string, a bool, null, NaN, an infinity), or an
  `isHard` that is not a boolean, is refused before any plan line. Before, it ended in
  `uncaught.exception`, sometimes after a `plan` line with `ok: true`, or compiled as if valid. An
  integer confidence beyond the float range is refused the same way, and a spec nested too deeply
  to parse is `dag_spec.unreadable`.

- **One `retryable` for every `gh.` and `git.` code** (flyingrobots/taskalisk#79). The
  `gh.response_invalid` remedy no longer says to rerun, since the code is not retryable;
  `SKILL.md` names both exceptions (`gh.list_limit_reached`, `gh.response_invalid`); the output
  reference gains the missing `root.invalid_reference` row. No flag, code or schema changes; the
  `gh.response_invalid` remedy text changed.

## 2.1.2 - 2026-11-24

### Changed

- **The vendored Parley writer is `parley_emit.py` 0.3.0** (flyingrobots/taskalisk#86), up from
  0.1.1, pinned by the digest on flyingrobots/parley's release `parley-emit-py-v0.3.0`. It
  implements Parley spec 0.2.1. What a caller of the skill can see:
  - a line in which a declared secret was replaced, and which no longer fits its schema, is
    withheld and the run ends with status 4 and a `redaction.schema_conflict` error; before, the
    line was published. The secrets Taskalisk declares are the `gh` token variables, and none of
    its messages carries one, so no ordinary run changes;
  - an incomplete receipt is kept for 24 hours before retention may delete it;
  - a `.parley/.gitignore` negation the writer cannot evaluate sends receipts to the state
    directory, with a `receipt.relocated` warning.
  No Taskalisk message, schema or exit status of its own changes. All fifteen of its schemas are
  ones the new writer can evaluate.

## 2.1.1 - 2026-11-24

### Added

- **A license: Apache-2.0** (flyingrobots/taskalisk#72). `LICENSE` and `NOTICE` at the root, and in
  the release archive as `taskalisk/LICENSE` and `taskalisk/NOTICE`. Earlier releases carried no
  license and so granted nothing. No behaviour or schema changes.

## 2.1.0 - 2026-11-23

### Added

- **Canonical issue templates** in `skills/taskalisk/templates/issue/`, one for each task `.type`,
  derived from Parley's and made project-neutral. Each opens with the frontmatter block and the six
  body sections `WRITING-TASKS.md` requires, in order. The skill says how to install them into a
  repository's `.github/ISSUE_TEMPLATE/`, and `tests/test_issue_templates.py` holds every template
  to the compiler's own frontmatter validator and to `WRITING-TASKS.md`'s section table.

## 2.0.0 - 2026-11-23

A breaking change to the output (flyingrobots/taskalisk#70). Running agents read the installed
copy's output, and the 1.x document is gone (decision 0002): update whatever parses it before
replacing an installed copy.

### Changed

- **Every line is JSON under a declared schema, written through Parley.** The single indented
  document is replaced by JSON Lines from the vendored Parley writer (spec 0.2): a bootstrap line,
  result lines, `parley.error` lines on stderr, and `end`. See `docs/topics/output/README.md`.
- **Exit statuses** follow Parley:

  | 1.x | 2.0 |
  | --- | --- |
  | 0 success | 0 |
  | 1 invalid frontmatter, cycle, unknown prerequisite, refused edit, unreadable DAG spec | 2, with a `parley.error` whose code says which (`frontmatter.invalid`, `graph.cycle`, `graph.unresolved_prerequisites`, `edge.*`, `dag_spec.*`) |
  | 1 bad edge syntax, self-edge; 2 a `--root` that is not `owner/repo#N` | 3, one `parley.startup.failed` line, no receipt: checked before the run starts |
  | 2 `gh` or `git` failure, truncation, trust lookup failure, root out of scope | 2, with codes `gh.*`, `git.*`, `root.*` (`retryable` true for a failed call) |
  | 2 argparse usage error, text on stderr | 3, one `parley.startup.failed` line |
  | traceback | 2, `uncaught.exception`; the traceback only in the receipt |

  New in 2.0: a missing or damaged schema file in an installed skill is a startup failure, exit 3,
  code `startup.declaration_unreadable`; a missing `scripts/parley_emit.py` is the one documented
  exception, Python's own import error and exit 1.

- **Where each 1.x field went:**

  | 1.x document | 2.0 lines |
  | --- | --- |
  | `ok`, `error` | `taskalisk.plan` `ok` and `error_codes`; the `parley.error` lines' `problem` |
  | `metrics`, `open_frontier_count` | `taskalisk.plan` `metrics`, `open_frontier_count` |
  | `open_frontier_ranked[]` | `taskalisk.frontier_node`, one per node, with `rank` and `score.terms`; ids in `taskalisk.plan` `frontier` |
  | `waves` | `taskalisk.wave` (ids per wave) and `taskalisk.node` (Wave 1 and later) |
  | `conflict_free_frontier_batch`, `batch_skipped`, `semaphores_with_unknown_capacity_treated_as_1` | `taskalisk.batch` `members`, `skipped`, `semaphores_with_unknown_capacity_treated_as_1`; ids in `taskalisk.plan` `batch` |
  | `edges[]` | `taskalisk.edge` |
  | `transitive_redundant_edges_removed[]` | `taskalisk.finding` `edge.redundant` |
  | `soft_or_low_confidence_edges[]` | `taskalisk.finding` `edge.soft_or_low_confidence` |
  | `unknown_dependencies[]`, `stale_merged_hints[]`, `cyclic_nodes[]` | findings `prerequisite.unknown`, `prerequisite.stale_merged_hint`, `graph.cyclic_node` |
  | `source.kind`, `schema`, `repository`, `roots`, `trust` | `taskalisk.plan` `source` |
  | `source.untrusted_issues[]` | finding `issue.untrusted` |
  | `source.untrusted_linked_prs[]` | finding `pull_request.untrusted` |
  | `source.unmodeled_open_issues[]` | finding `issue.unmodeled` |
  | `source.opaque_nodes[]` | finding `issue.opaque` |
  | `source.containers_excluded[]` | finding `container.excluded` |
  | `source.not_planned_parents[]` | finding `parent.not_planned` |
  | `frontmatter.violations`, `frontmatter.warnings` | findings `frontmatter.violation`, `frontmatter.warning` (`subject` is the issue); the count in `taskalisk.plan` `violating_issues` |
  | `relationship_drift` | `taskalisk.plan` `relationships.in_sync`; findings `relationship.only_in_frontmatter`, `relationship.only_in_github` |
  | `github_errors[]` | one `parley.error` each, `detail: {source, error, phase}` |
  | `mutation` | `taskalisk.edge_edit` |
  | `meta.artifact_hash` | `taskalisk.plan` `artifact_hash` (the same value) |
  | `--emit-roadmap`, `--emit-mermaid` text on stdout | `taskalisk.rendering` `text`; `--human` prints it as is |
  | inventory `worktrees`, `unmerged_branches`, `github.open_prs`, `github.open_issues`, `inventory_errors` | `taskalisk.inventory.summary`, `.worktree`, `.branch` (`scope`), `.pull_request`, `.issue`; `parley.error` |

- A failed `--compare-relationships` lookup no longer reports a drift computed from a partial
  read; the plan line's `relationships.in_sync` is null and the errors say why.
- `--emit-roadmap` with `--emit-mermaid`, and `--emit-mermaid` in inventory, are usage errors
  (1.x ignored one of them).
- A `--verify-dag` node whose `title`, `type`, `workstream`, `url`, `holds`, `meters` or
  `size_hours` has the wrong type is a `dag_spec.invalid` error (1.x crashed or printed it).
- Arguments, references included, are validated before the run starts (Parley spec 3.2): a bad
  edge, a self-edge or a malformed `--root` makes no `gh` call and leaves no receipt.

### Fixed

- A line break in an issue title no longer ends a Mermaid node label and starts a line of its own
  in the rendered diagram (threat model C5).

### Added

- Commands `plan`, `edit`, `verify` and `inventory`; the 1.x mode flags still select them.
- Fifteen message schemas at 1.0.0: `taskalisk.plan`, `taskalisk.frontier_node`, `taskalisk.node`,
  `taskalisk.wave`, `taskalisk.batch`, `taskalisk.edge`, `taskalisk.finding`, `taskalisk.edge_edit`,
  `taskalisk.rendering`, `taskalisk.frontier_change`, `taskalisk.inventory.summary`,
  `taskalisk.inventory.worktree`, `taskalisk.inventory.branch`,
  `taskalisk.inventory.pull_request`, `taskalisk.inventory.issue`.
- A frontier node states its score's terms (`in_flight`, `parked`, `descendants`,
  `critical_path_depth`, `out_degree`) with their weights.
- `--help` and `--schema` as JSON Lines; `--human` prints a ranked table and the findings.
- `--since-last`: the frontier's changes since the previous receipt of the same question.
- `edit --dry-run`: checks an edge edit and writes nothing.
- A receipt per run under `.parley/receipts/`, with a step for each lookup and trust decision,
  and issue bodies recorded as a declared input by id and digest only.
- `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN` and `GITHUB_ENTERPRISE_TOKEN` are declared
  secrets; a credential inside a URL in `gh` or `git` output is redacted.
- The vendored writer `scripts/parley_emit.py` is the released `parley_emit.py` 0.1.1
  (flyingrobots/parley tag `parley-emit-py-v0.1.1`), pinned by `scripts/parley_emit.pin.json`; it
  ships in the release and its `SHA256SUMS`. That version takes the command by position, ends its
  own flags at `--`, keeps receipts out of a checkout whose `.parley/.gitignore` re-includes them,
  and publishes schema documents unscrubbed.
- `verify` records a DAG file it could not read as an unread input under `dag_spec.unreadable`,
  with no `inv`; a file that was read but is not JSON is recorded by the bytes read.

## 1.0.0 - 2026-11-15

The first release: the skill as a self-contained ZIP with per-file checksums (#55).
