<!-- BEGIN GENERATED ISSUE DAG (taskalisk --emit-roadmap; do not edit by hand) -->

Compiled from issue frontmatter (`issue-dag/2`), home `o/r`, roots `o/r#1`. Artifact hash `75c885cf54bc599d`. Regenerate with `taskalisk.py --from-github [--root <ref>] --emit-roadmap`.

## DAG Structural Health

| Metric | Value |
| --- | --- |
| Open nodes | 2 |
| Reduced edges (raw) | 1 (1) |
| Edge density | 1.0 (outside band 0.01–0.50) |
| Max parallel width | 1 |
| Critical path (2) | o/s#2 → o/r#1 |
| Isolated nodes | 0 |
| Containers excluded | none |

## Ranked Open Frontier (Wave 0)

| Rank | Score | Issue | Title | Status | Unblocks | Depth | Resources | Directly unlocks |
| ---: | ---: | --- | --- | --- | ---: | ---: | --- | --- |
| 1 | 121 | [o/s#2](https://github.com/o/s/issues/2) | (title not recorded) | open | 1 | 2 | — | o/r#1 |

### Conflict-Free git-locks Batch

- [o/s#2](https://github.com/o/s/issues/2) (title not recorded) — no resources

## Task Checklist by Wave

### Wave 0

- [ ] [o/s#2](https://github.com/o/s/issues/2) (title not recorded) (open)

### Wave 1

- [ ] [o/r#1](https://github.com/o/r/issues/1) (title not recorded) (open)

## Task Checklist by Workstream (`area:*`)

### feature

- [ ] [o/r#1](https://github.com/o/r/issues/1) (title not recorded)
- [ ] [o/s#2](https://github.com/o/s/issues/2) (title not recorded)

## Transitively-Reduced Dependency DAG

```mermaid
flowchart TD
  subgraph Wave0["Wave 0: Open Frontier (Zero Incomplete Parents)"]
    N_o_s_2["o/s#2: (title not recorded)"]
  end
  subgraph Wave1["Wave 1"]
    N_o_r_1["o/r#1: (title not recorded)"]
  end
  N_o_s_2 --> N_o_r_1
```

## Prerequisite Edge Accounting

| Blocker | Blocked | Evidence |
| --- | --- | --- |
| o/s#2 | o/r#1 | frontmatter: o/r#1 .blocked_by o/s#2 |

<!-- END GENERATED ISSUE DAG -->