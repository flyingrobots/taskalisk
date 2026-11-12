# Change Taskalisk and verify the result

Taskalisk admits external data before it constructs a graph. The graph computes
precedence and resource allocation; rendering presents that result. Command
routing owns effects. Keep those boundaries visible when changing the compiler.

Start with [AGENTS.md](AGENTS.md), the [format](docs/frontmatter-model.md), and the
[threat model](docs/threat-model.md). Compile the repository's backlog and take a
frontier issue. Its body owns scope, acceptance checks and test plans. Work on a
branch with a draft PR; record discovered dependencies using Taskalisk's edge
command. A compiler change also needs read-only live-backlog verification.

## Verify a change locally

The CLI at `skills/taskalisk/scripts/taskalisk.py` has no runtime package
dependencies. Development uses the locked environment in `pyproject.toml` and
`uv.lock`. Install uv 0.12.19, then prepare that environment from the repository
root. Installation uses the network; behavioral tests use the offline provider.

```sh
uv sync --locked --no-editable --group dev
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync pyright
uv run --no-sync python -m tools.check_structure
uv run --no-sync python -m coverage erase
uv run --no-sync python -W error -m coverage run -m unittest discover -s tests
uv run --no-sync python -m coverage combine
uv run --no-sync python -m coverage json -o coverage.json
uv run --no-sync python -m tools.check_coverage coverage.json
```

Run these in an owned checkout with finite execution and storage budgets. The
coverage erase step removes earlier measurement files in that checkout, so a
prior run cannot fill gaps in the current one. Subprocess attribution is enabled
in `pyproject.toml`; running only the parent test process is insufficient. Inspect
each command's exit status. A failed gate is not repaired by a passing last line.

The structure checker emits JSON with source hashes, measurements and findings.
The coverage checker reports each deficient file and measure separately, using
unrounded counts: critical scopes need 95% statements and 95% branches; other
maintained Python needs 90% of each. A genuinely branchless file has no branch
opportunities. Missing executable source or missing measurement fails the gate.

Gate adoption is still in progress under [#22](https://github.com/flyingrobots/taskalisk/issues/22).
Coverage gaps, final scope/exception enforcement, documentation/tool freshness,
optimized probes and the complete quality CI matrix remain open obligations.
The current workflow runs the offline behavioral suite on pinned CPython
3.9–3.13 versions on Linux and macOS; its success alone is not full acceptance.
The exact pins live in [.github/workflows/test.yml](.github/workflows/test.yml).

## Keep evidence tied to behavior

Write a discriminating failing witness before repairing behavior, then retain a
passing control. Calibrate new load-bearing assertions with deliberate faults
in an owned copy: an assertion must reject the intended defect, rather than a
setup error, missing executable or unrelated traceback. Record the source
identity, command, interpreter, result and limits for both RED and GREEN.

Use the public CLI for admission, output and mutation contracts. Use real Git
for filesystem/ref observations. `tests/fake_gh.py` is the prescribed offline
provider, with independent fixture constructors and a call log. Its tests must
prove the relevant protocol behavior; it cannot establish live GitHub atomicity,
authentication behavior or cancellation of a remote effect. The test harness's
direct-child deadlines do not contain arbitrary descendant processes.

For generated cases, retain the chosen seeds, finite bounds, observed corpus and
shrinking configuration. A bounded differential corpus supports the paths it
observed; it is not universal equivalence. Re-run the appropriate acceptance
checks after changing a measured source. Do not reuse stale evidence as green.

## Find the owning boundary

Modules below are under `skills/taskalisk/scripts/taskalisk_core/` unless noted.
This map identifies risks and representative witnesses, not proof that every
failure mode is tested. The [architecture decision](docs/decisions/0001-python-verification.md)
defines the measurements, limits and known boundaries in more detail.

| Change | Owning modules | Invariant and representative evidence |
| --- | --- | --- |
| External commands | `process`, `process_capture`, `process_exit` | Bound input/output and waiting; retain process ownership. `test_process_contract`, `test_process_lifetime`, `test_process_ownership`. |
| GitHub data | `github`, `github_*_values`, `github_json`, `github_history` | Admit the whole checked response or report failure; never coerce actor identity. `test_github_*`, `test_provider_failures`. |
| Trust and discovery | `authorization`, `identities`, `discovery_*` | Scope before fetch; author before editors; untrusted content contributes no task metadata. `test_actor_trust`, `test_discovery_*`. |
| Format and local input | `frontmatter`, `issue_refs`, `spec_*` | Preserve explicit identities and reject invalid scalars/resources before analysis. `test_frontmatter_contract`, `test_spec_*`, `test_validation`. |
| Graph and resources | `graph`, `graph_dependencies`, `graph_structure`, `graph_ranking`, `graph_resources` | Preserve reachability, precedence, ranking and resource constraints. `test_graph_properties`, `test_resources`, `test_plan_presentations`. |
| Effects and output | `cli*`, `modes*`, `output`, `rendering` | Validate options before effects; retain failure evidence and escaped display text. `test_mutation_*`, `test_cli_options`, `test_rendering_trust`. |
| Local inventory | `inventory`, `inventory_worktrees` | Distinguish missing, unknown and observed Git state. `test_worktree_inventory`, `test_inventory_cli`; symbolic remote-HEAD correction is owned by #15. |
| Verification tools | `tools/check_coverage`, `tools/check_structure`, `tools/source_*` | Refuse missing or malformed evidence and expose exact measurements. `test_coverage_gate`, `test_structure_*`, `test_source_structure`. |

## Submit a reviewable result

Keep changes scoped to the issue and preserve unrelated work. Never bypass
hooks or rewrite shared history. Every suppression or exception needs the
smallest scope, reason, risk, compensating evidence, owner, approver and expiry
in [exceptions.json](exceptions.json); an entry alone is not enforcement.

Report what passed, what remains untested and which source was measured. When
acceptance and CI pass, mark the PR ready for review. Merge requires Baker Street
`READY`, zero unresolved threads or open review requests, and green checks.
After merge, recompile the task graph before selecting the next frontier task.
