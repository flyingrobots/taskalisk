# Output contract: test plan

The contract ledger for [the output contract](README.md) (flyingrobots/taskalisk#70). Each row
is a requirement with a stable ID, the case that exercises it, the oracle that decides it, and the
test that implements it. Status is `planned` until a test exists, then `implemented`.

The suite runs offline: `python3 -m unittest discover -s tests`. The Parley doctor is not
available in CI; the doctor rows are checked locally on captured runs, and the captured runs are
committed and re-validated offline (OUT-19).

| ID | Requirement | Case | Oracle | Status | Test |
| --- | --- | --- | --- | --- | --- |
| OUT-01 | Every line on stdout and stderr, and every receipt line, validates against the schema its `_schema` names | Every mode (plan, edit, verify, inventory, discovery) and every error path below | The vendored writer's `validate_line` with the tool schemas; a pair with no schema fails | planned | |
| OUT-02 | The lines carry everything the 1.x document did | Every scenario in `tests/golden_scenarios.py`, captured from `6e84058` | A reconstruction rebuilds the old document from the lines and compares equal; `plan.artifact_hash` equals the old `meta.artifact_hash` | planned | |
| OUT-03 | Line order: bootstrap, then the plan, the frontier in rank order, the batch, then the rest; `end` last | `plan_rich` | Event order on stdout | planned | |
| OUT-04 | A frontier node states its score and each term | `plan_rich` (in flight, parked, descendants, depth, out-degree all non-zero somewhere) | `score.total == priority_score == sum(points)`, `points == value * weight` | planned | |
| OUT-05 | Every failure the 1.x compiler had is a typed `parley.error` with a stable code, exit 2 | gh failure, list limit, invalid frontmatter, cycle, unresolved prerequisites, bad edge syntax, self-edge, refused edit, failed write with restore, unreadable DAG spec | Code on stderr, exit status 2, `end.status` 2 | planned | |
| OUT-06 | A usage error is a startup failure | Conflicting flags, a bad `--sem-capacity` | Exit 3, one `parley.startup.failed` line on stderr, nothing on stdout | planned | |
| OUT-07 | `--help` and `--schema` are runs that describe every command and schema | `--schema`; `plan --help`; `--from-github --help` | `command` and `schema` lines, every tool schema present, exit 0 | planned | |
| OUT-08 | `--human` prints a compact ranked table and findings, no JSON | `plan_rich --human` | No stdout line parses as JSON; the receipt validates | planned | |
| OUT-09 | `--since-last` reports a promotion after a blocker closes, from the receipts alone | Two runs; the blocker closes between them | `frontier_change` `promoted`; the second run makes no extra `gh` call for it | planned | |
| OUT-10 | No declared secret reaches any stream or the receipt | `GH_TOKEN` set and echoed by a failing `gh`; a token in a URL | The value is absent from stdout, stderr and receipt; `redacted.env` names the variable | planned | |
| OUT-11 | Nothing an untrusted author wrote reaches any line, and the receipt records issue bodies by digest and id only | An untrusted seed and an untrusted opaque blocker with marked titles and bodies | The markers are absent from all three streams; the observation step carries ids and digests | planned | |
| OUT-12 | A title cannot forge or break a line | A title holding a newline, a JSON object and control characters | Every stdout line parses; in `--human`, no control character reaches stdout | planned | |
| OUT-13 | No traceback reaches stderr | An exception inside the compiler | `uncaught.exception` on stderr; the traceback only in the receipt | planned | |
| OUT-14 | An empty backlog compiles | No open issues | `plan` with an empty frontier, exit 0 | planned | |
| OUT-15 | An added edge that makes a cycle is restored | `edit_cycle` | Body restored; `edge_edit.rolled_back` true; `graph.cycle`; exit 2 | planned | |
| OUT-16 | A thousand-issue backlog streams in a stated time | A 1000-node `--verify-dag` spec | Finishes within 60 s; no line over 65,536 bytes; one line per node | planned | |
| OUT-17 | The vendored writer is pinned by digest and ships in the release | The copy and `parley_emit.pin.json`; a built release | Digests agree; the archive and its `SHA256SUMS` hold the writer | planned | |
| OUT-18 | Machine-local paths stay out of the output as before | Inventory worktree paths and `gh` error text under the home directory | The home directory is shown as `~` | planned | |
| OUT-19 | Captured real runs pass the Parley doctor, and stay valid offline | Captured runs of plan, inventory, edit, a `gh` failure, `--help`, `--schema` and `--human` | Doctor run locally (PR states the runs); the suite re-validates every committed line | planned | |
| OUT-20 | The existing suite's assertions about what is computed still hold | `tests/test_taskalisk.py`, unchanged assertions, read through the reconstruction | The assertions | planned | |
| OUT-21 | The skill's recipe for the ranked frontier works on real output | The recipe in `SKILL.md` run over a captured plan | It prints the frontier ids in rank order | planned | |
| OUT-22 | `edit --dry-run` writes nothing | A dry-run add | No `PATCH` call; `edge_edit.dry_run` true | planned | |
