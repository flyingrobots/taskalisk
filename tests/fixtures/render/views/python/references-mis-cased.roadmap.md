<!-- BEGIN GENERATED ISSUE DAG (taskalisk --emit-roadmap; do not edit by hand) -->

Compiled from issue frontmatter (`issue-dag/2`), home `flyingrobots/geordi`, roots `flyingrobots/geordi#1`. Artifact hash `d5634ad9feb9e567`. Regenerate with `taskalisk.py --from-github [--root <ref>] --emit-roadmap`.

## DAG Structural Health

| Metric | Value |
| --- | --- |
| Open nodes | 2 |
| Reduced edges (raw) | 1 (1) |
| Edge density | 1.0 (outside band 0.01–0.50) |
| Max parallel width | 1 |
| Critical path (2) | flyingrobots/echo#5 → flyingrobots/geordi#1 |
| Isolated nodes | 0 |
| Containers excluded | none |

## Ranked Open Frontier (Wave 0)

| Rank | Score | Issue | Title | Status | Unblocks | Depth | Resources | Directly unlocks |
| ---: | ---: | --- | --- | --- | ---: | ---: | --- | --- |
| 1 | 121 | [flyingrobots/echo#5](https://github.com/flyingrobots/echo/issues/5) | (title not recorded) | open | 1 | 2 | — | flyingrobots/geordi#1 |

### Conflict-Free git-locks Batch

- [flyingrobots/echo#5](https://github.com/flyingrobots/echo/issues/5) (title not recorded) — no resources

## Task Checklist by Wave

### Wave 0

- [ ] [flyingrobots/echo#5](https://github.com/flyingrobots/echo/issues/5) (title not recorded) (open)

### Wave 1

- [ ] [flyingrobots/geordi#1](https://github.com/flyingrobots/geordi/issues/1) (title not recorded) (open)

## Task Checklist by Workstream (`area:*`)

### feature

- [ ] [flyingrobots/echo#5](https://github.com/flyingrobots/echo/issues/5) (title not recorded)
- [ ] [flyingrobots/geordi#1](https://github.com/flyingrobots/geordi/issues/1) (title not recorded)

## Transitively-Reduced Dependency DAG

```mermaid
flowchart TD
  subgraph Wave0["Wave 0: Open Frontier (Zero Incomplete Parents)"]
    N_flyingrobots_echo_5["flyingrobots/echo#5: (title not recorded)"]
  end
  subgraph Wave1["Wave 1"]
    N_flyingrobots_geordi_1["flyingrobots/geordi#1: (title not recorded)"]
  end
  N_flyingrobots_echo_5 --> N_flyingrobots_geordi_1
```

## Prerequisite Edge Accounting

| Blocker | Blocked | Evidence |
| --- | --- | --- |
| flyingrobots/echo#5 | flyingrobots/geordi#1 | frontmatter: flyingrobots/geordi#1 .blocked_by flyingrobots/echo#5 |

<!-- END GENERATED ISSUE DAG -->