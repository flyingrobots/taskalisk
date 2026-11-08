---
name: issue-dag
description: >-
  Compile GitHub issues and their native blocked_by/blocking dependencies into
  a minimal, transitively-reduced precedence DAG with zero local state; rank
  the live Open Frontier (zero open blockers) by transitive unblocking power
  and critical-path depth; compute prefix-aware conflict-free git-locks
  dispatch batches from lock:* labels; and record new edges as GitHub
  dependencies. Use whenever the user asks to plan a milestone, map issue
  dependencies, build an execution DAG, audit unmerged branches/worktrees, or
  identify and prioritize open frontier nodes.
---

# issue-dag

GitHub is the single source of truth. Issues are the tasks, native issue
dependencies (`blocked_by` / `blocking`) are the hard precedence edges,
labels carry the adjacent `git-locks` resource catalog, and GitHub's own
timeline is the provenance ledger. The skill keeps **zero local state**: no
task-file frontmatter, no cached graph, no JSONL ledger. Every run recompiles
from GitHub and every mutation is a GitHub write.

Resolve the helper script relative to this skill's directory
(`<this-skill>/scripts/issue_dag_snapshot.py`). Never hardcode machine-local
absolute paths in tracked documentation.

This is the T.A.S.K.S. + S.L.A.P.S. model mapped onto GitHub: `tasks.json` is
the issue set (house card templates give boundaries, acceptance checks and
definition of done), `dependencies` are the recorded `blocked_by` relations,
the resource catalog is the `lock:*` label set, waves are a planning-time
forecast, the frontier rolls at execution time, and the ledger is append-only
because GitHub's timeline is.

---

## Core Doctrine

1. **DAG Purity (Precedence $\neq$ Resource Contention)**
   - An edge $(u \to v)$ exists only when GitHub records *u blocks v*. It means
     "u must be closed (merged) before v is correct and leaves `main` green".
   - Labels, milestones, shared files, topic similarity, and tracking
     containers (`type:goalpost`) never create edges. A container that appears
     as a blocker is ignored.
   - Resource constraints are modeled **adjacent to** the graph via
     `git-locks` keys read from `lock:*` labels (e.g. `lock:host/heavy-work`,
     `lock:docs/`, `lock:scripts/`, `lock:host/docker/<worker>/`). Without a
     `lock:*` label the key is derived from `area:*` (`area:docs` → `docs/`,
     `area:tooling` → `scripts/`, else `host/heavy-work`) and the output says
     which rule applied. Keys are lexical; a trailing `/` claims a subtree,
     so `docs/` conflicts with `docs/plans/`. The batch is advice; admission
     is the `git locks with` call.
2. **One Executable Node = One Issue = One Independently Mergeable Change**
   - If a PR implements a proper subset of an issue, either the issue is the
     unit and the PR is a slice of it (the issue stays open until the last
     slice merges), or the slices become sub-issues with their own
     `blocked_by` edges. Do not invent slice ids that GitHub cannot see.
3. **Typed, Evidence-Backed Edges**
   - Every compiled edge cites the GitHub dependency record. Completed parents
     cite the closed issue's state and `state_reason`; parents closed as
     `not_planned` are listed separately for review because GitHub still
     treats them as satisfied.
   - A PR cannot be a blocker on GitHub. Model a PR-level prerequisite as a
     dependency on the PR's issue, or split the issue into sub-issues.
   - **No recorded blockers is not proof of independence.** Read issue bodies,
     review follow-ups, and unmerged branches; when you find a real
     prerequisite, record it with `--add-edge` so the truth source has it.
4. **Transitive Reduction & Graph Health Metrics**
   - Redundant edges $(u \to v)$ implied by $u \leadsto w \leadsto v$ are
     removed from the compiled graph and listed; they may stay recorded on
     GitHub as evidence.
   - Audit **Edge Density** (band `0.01–0.50`), **Max Parallel Width**,
     **Critical Path**, and **Isolated Nodes**. Many isolated nodes means the
     dependencies have not been recorded yet, not that the work is independent.
   - **Fail closed.** Any `gh`/`git` failure, unparseable JSON, or a list
     result that fills its query limit exits `2`; a cycle exits `1`. Never
     treat a failed query as an empty backlog.
5. **Waves as Forecast, Rolling Frontier as Executor**
   - Kahn waves (`Wave 0..N`) are a planning-time view of parallel width.
   - At execution time Wave 0 (the Open Frontier) rolls: the moment a blocker
     is closed on GitHub, the next run promotes its children. Nothing is
     written down to make that happen.
6. **Never Publish Machine-Local Absolute Paths**
   - In `ROADMAP.md`, issue bodies, or any tracked output, use `~`, `$HOME`,
     or repository-relative paths.
7. **Strict Gate Integrity & Read-Only Boundaries**
   - `--from-github` without `--add-edge`/`--remove-edge`, `--verify-dag`, and
     the inventory mode are strictly read-only. The only GitHub writes the
     script performs are dependency records, and an `--add-edge` that creates
     a cycle is removed again before the run fails.
   - Never resolve review threads without a verifying fix and never push to
     `origin/main` to bypass PR checks.

---

## CLI Tooling (`scripts/issue_dag_snapshot.py`)

1. **GitHub-native DAG (read-only):**
   ```bash
   python3 <this-skill>/scripts/issue_dag_snapshot.py --from-github [--milestone v21.0.0] [--emit-mermaid]
   ```
   Lists open issues (containers excluded), fetches each issue's recorded
   `blocked_by` set (open blockers outside the milestone filter are pulled in
   as nodes because precedence is about correctness, not scope), marks an
   issue in flight when it carries `status:active` or has an open linked PR,
   compiles the reduced DAG, ranks the frontier, and proposes a conflict-free
   batch. An issue labeled `status:parked` (started, stopped, recoverable
   branch exists) scores +500: resuming beats restarting, but in-flight work
   still ranks first. Each node lists `recoverable_branches` whose names
   contain its number. Every node's body is checked against the house card
   standard (`# <Type>` heading, ```` ```text ```` execution prompt, sections
   1-9, no machine-local paths); pass `--require-house-format` to fail the run
   when any open node violates it. Use that flag as the gate before dispatch. Output includes `source.containers_excluded`,
   `source.external_open_blockers`, `source.not_planned_parents`, `edges`
   with evidence, and an `artifact_hash` of the canonical result.

2. **Record or remove an edge on GitHub:**
   ```bash
   python3 <this-skill>/scripts/issue_dag_snapshot.py --from-github \
     --add-edge "#1080->#1052" --reason "Coordinate contract must land before Optic reads"
   python3 <this-skill>/scripts/issue_dag_snapshot.py --from-github --remove-edge "#1080->#1052"
   ```
   `#parent->#child` means *parent blocks child*. The script writes the
   dependency, recompiles, and if the graph is now cyclic deletes the
   dependency again and exits `1`. GitHub's issue timeline is the ledger; the
   `--reason` is echoed in the output for the operator's own record (put it in
   the issue comment or PR body if it matters).

3. **Render the ROADMAP block (read-only):**
   ```bash
   python3 <this-skill>/scripts/issue_dag_snapshot.py --from-github --milestone v21.0.0 --require-house-format --emit-roadmap
   ```
   Prints the generated section of `ROADMAP.md`, between
   `<!-- BEGIN GENERATED ISSUE DAG ... -->` and `<!-- END GENERATED ISSUE DAG -->`:
   health metrics, ranked frontier, conflict-free batch, checklists by wave and
   by `area:*`, the Mermaid DAG, and edge accounting with evidence. Replace the
   marked section wholesale; keep the executive summary and worktree audit
   above and below it hand-written.

4. **Verify a hand-written DAG specification (read-only):**
   ```bash
   python3 <this-skill>/scripts/issue_dag_snapshot.py --verify-dag dag.json [--min-confidence 0.7] [--emit-mermaid]
   ```
   For what-if planning. The spec is input, not state.

5. **Full-spectrum inventory (read-only, fail-closed):**
   ```bash
   python3 <this-skill>/scripts/issue_dag_snapshot.py --repo /path/to/repo [--milestone v21.0.0]
   ```
   Worktrees (dirty, ahead/behind, missing checkouts), unmerged local and
   remote branches, open PRs with the issues they close, open issues.

Priority for frontier nodes:
$$\text{PriorityScore}(u) = 1000 \cdot \text{InFlight}(u) + 500 \cdot \text{Parked}(u) + 100 \cdot |\text{Descendants}(u)| + 10 \cdot \text{CriticalPathDepth}(u) + d_{\text{out}}(u)$$

---

## Workflow

### Step 1: Gather Full-Spectrum Inventory
Run the inventory and the GitHub-native DAG. Also read: open and recently
closed issues in and outside the milestone, open and prototype PRs, every
worktree, unmerged branches, and tracked design docs under `docs/plans/`.

### Step 2: Reconcile Baseline & Classify Nodes
- **Completed baseline:** closed issues and merged PRs. Verify a claimed
  "merged" against GitHub, never against a document.
- **Executable open nodes:** open non-container issues.
- **Superseded / historical branches:** record their disposition in the
  branch audit table so they are not mistaken for missing work.

### Step 3: Record Missing Edges, Then Compile
For every open node, ask which issues must already be closed for it to be
correct on a green `main`. Where GitHub does not yet record that, add it with
`--add-edge` (evidence in the issue comment). Then recompile and inspect
`metrics.critical_path`, `metrics.max_parallel_width`,
`metrics.edge_density`, and `metrics.isolated_open_nodes`. If a cycle appears
between two whole issues, split the shared foundation into a predecessor
issue.

### Step 4: Rank the Frontier & Compute the Conflict-Free Batch
Wave 0 is every open node with zero open blockers. Add `lock:*` labels where
the derived default is wrong. The conflict-free batch is what several agents
can run concurrently; each still claims its keys with `git locks with`.

### Step 5: Write or Update `ROADMAP.md`
`ROADMAP.md` is a rendered view, regenerated from the compiled DAG, never a
second tracker: an ASD-STE100 executive summary; the ranked Open Frontier
table (rank, issue link, transitive unblocks, critical-path depth, locks,
directly unlocks); the sequenced `- [ ]` checklist by wave and by `area:*`
workstream, each item linking to its GitHub issue; the worktree and branch
audit table; the `--emit-mermaid` diagram; and the edge accounting table with
evidence. Issue bodies, written with the house card templates in
`.github/ISSUE_TEMPLATE/`, are the task plans.

### Step 6: Keep the Truth Source Current
When execution or review discovers a dependency, record it with `--add-edge`
immediately. When a slice merges, close the issue (or the sub-issue) on
GitHub; the next run promotes its children. Do not maintain wave numbers,
unlock lists, or status fields anywhere by hand.
