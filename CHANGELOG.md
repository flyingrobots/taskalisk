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
  of the vendored corpus pass; for each `--python` twin the crate matches the normative case. Pending
  their specification text: a key repeated under C7 is present but judged by no other rule, while the
  rest of the document is judged; a repeated `.dag` leaves the version unknown, so C7 is the
  document's only violation, as C4 and P3 stop judging; an invalid document reports no warnings. CI
  runs the job "Rust workspace": `cargo fmt`, `clippy -D warnings` and `cargo test`, all locked.

- **Repeated keys, warnings and refusal order in the specification** (flyingrobots/taskalisk#104).
  The vendored issue-dag specification now states the rulings the Rust core implements: no rule of
  sections 3 to 5 labels a repeated key, so labels never depend on line order, while its lines keep
  their C6 and C8 labels; a repeated `.dag` gives C7 as the document's only violation; V10 warns
  only on a document with no violation, X1 included; edge-edit rule E3a refuses an invalid document,
  then a non-task, then a self edge; CC5 sorts labels by their UTF-8 bytes and lets an invalid
  result hold `"warnings": []`. The corpus gains 17 normative cases and 12 `--python` twins
  (differences 4, 19, 20, 21 and 22), digest `sha256:7204de0f…`.

- **Document findings with stable codes** (flyingrobots/taskalisk#43). `issue-dag-core`
  judges a body with its issue's address, so rule X1 always applies, and returns findings: a stable
  code, a severity (error, or warning for the V10 advisory), the address as subject, and a message.
  A code is the rule's V12 label prefixed by the specification that states it: `format.C4` to
  `format.V10`, `version.P3` and `profile.X1`, tabled on `code` in the crate docs.
  Findings sort by subject, then code text. A message is fixed text that names keys and rules only,
  never a value or a line of the body; a body without a document has no findings.

- **A provenance check for the vendored Parley writer** (flyingrobots/taskalisk#77).
  `scripts/check_vendored_writer.py` fetches the writer from flyingrobots/parley at the pinned
  commit and requires it to equal the pin and the copy; CI runs it. The offline pin test proves
  only that copy and pin agree, and the output reference now says which check proves what.

### Fixed

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
