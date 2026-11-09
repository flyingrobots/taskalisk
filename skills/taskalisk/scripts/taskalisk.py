#!/usr/bin/env python3
"""
taskalisk.py

Taskalisk: zero-local-state DAG compiler for issue frontmatter. Issue frontmatter
(`issue-dag/2`, see docs/frontmatter-model.md) is the single source of truth:
each issue's first fenced `yaml` block declares its kind, its `.blocked_by`
edges, its container `.children`, and the resources it holds. Labels,
milestones, body sections, and GitHub relationships never create edges.
Every issue reference is `owner/repo#N`; a bare `#N` is invalid,
because transferring an issue would silently re-point it. Nothing is
cached or written on disk.

Modes:
  --from-github [--root <ref>] [--emit-mermaid] [--emit-roadmap]
      Read-only. Discovers the closure from the open home issues (or the
      roots) through `.blocked_by` and `.children`, across repositories,
      compiles the transitively-reduced DAG, ranks the Open Frontier, and
      proposes a batch that respects `.holds` and `.meters`.
      Trust flags: --trust <login>, --trust-owner <owner>, --trust-repo
      <owner/repo>, --trust-codeowners (docs/threat-model.md).
  --from-github --add-edge "owner/repo#1080->owner/repo#1052" [--reason "..."]
      Adds the parent to the child's frontmatter `.blocked_by`, then
      recompiles. If the edge creates a cycle the old body is restored and
      the run fails.
  --from-github --remove-edge "owner/repo#1080->owner/repo#1052"
      Removes the parent from the child's `.blocked_by`.
  --from-github --compare-relationships
      Also reports drift between frontmatter edges and GitHub blocked_by
      relationships, which are an optional mirror.
  --verify-dag dag.json [--min-confidence 0.7] [--emit-mermaid]
      Read-only. Compiles a hand-written DAG specification (input, not state).
  --repo <path> [--milestone v21.0.0]
      Read-only. Full-spectrum inventory: worktrees, unmerged branches, open
      PRs, open issues. Exit 2 on any tool failure or possible truncation.

Guarantees:
1. DAG purity: only frontmatter `.blocked_by` entries enter the graph.
2. Fail closed: any `gh`/`git` failure, unparseable JSON, or list result that
   fills its query limit is an error (exit 2), never an empty backlog.
3. Edges come with evidence: each edge cites the frontmatter that declares it.
   Completion comes only from the GitHub issue state.
4. Strict frontmatter: an unknown `.` key, a wrong `.id`, a container used as
   a blocker, or a malformed value fails the run (exit 1).
5. Lexical lock conflicts: `.holds` keys are lexical; a trailing `/` claims a
   subtree, so `docs/` conflicts with `docs/plans/`. A semaphore with unknown
   capacity counts as exclusive.
6. Trust gate (docs/threat-model.md): an issue is a node only when its
   repository is in the trusted scope and its author and every body editor
   are trusted. A linked PR counts only from a same-repository branch by a
   trusted author. Untrusted issues and PRs are listed, never dispatched, and
   contribute nothing to the graph or to rendered output. Any trust lookup
   that cannot run (edit history, permission, CODEOWNERS) exits 2.
"""

import sys

from taskalisk_core.cli import main

if __name__ == "__main__":
    sys.exit(main())
