<!-- BEGIN GENERATED ISSUE DAG (taskalisk --emit-roadmap; do not edit by hand) -->

Compiled from issue frontmatter (`issue-dag/2`), home `o/r`, roots `all open home issues`. Artifact hash `376155f2e4efe79e`. Regenerate with `taskalisk.py --from-github [--root <ref>] --emit-roadmap`.

## DAG Structural Health

| Metric | Value |
| --- | --- |
| Open nodes | 2 |
| Reduced edges (raw) | 1 (1) |
| Edge density | 1.0 (outside band 0.01–0.50) |
| Max parallel width | 1 |
| Critical path (2) | o/r#2 → o/r#1 |
| Isolated nodes | 0 |
| Containers excluded | none |

## Ranked Open Frontier (Wave 0)

| Rank | Score | Issue | Title | Status | Unblocks | Depth | Resources | Directly unlocks |
| ---: | ---: | --- | --- | --- | ---: | ---: | --- | --- |
| 1 | 121 | [o/r#2](https://github.com/o/r/issues/2) | (untrusted issue) | blocked | 1 | 2 | — | o/r#1 |

### Conflict-Free git-locks Batch


## Task Checklist by Wave

### Wave 0

- [ ] [o/r#2](https://github.com/o/r/issues/2) (untrusted issue) (blocked)

### Wave 1

- [ ] [o/r#1](https://github.com/o/r/issues/1) (title not recorded) (open)

## Task Checklist by Workstream (`area:*`)

### feature

- [ ] [o/r#1](https://github.com/o/r/issues/1) (title not recorded)

### unassigned

- [ ] [o/r#2](https://github.com/o/r/issues/2) (untrusted issue)

## Transitively-Reduced Dependency DAG

```mermaid
flowchart TD
  subgraph Wave0["Wave 0: Open Frontier (Zero Incomplete Parents)"]
    N_o_r_2["o/r#2: (untrusted issue)"]
  end
  subgraph Wave1["Wave 1"]
    N_o_r_1["o/r#1: (title not recorded)"]
  end
  N_o_r_2 --> N_o_r_1
```

## Prerequisite Edge Accounting

| Blocker | Blocked | Evidence |
| --- | --- | --- |
| o/r#2 | o/r#1 | frontmatter: o/r#1 .blocked_by o/r#2 |

<!-- END GENERATED ISSUE DAG -->