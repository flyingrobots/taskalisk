<!-- BEGIN GENERATED ISSUE DAG (taskalisk --emit-roadmap; do not edit by hand) -->

Compiled from issue frontmatter (`issue-dag/2`), home `flyingrobots/geordi`, roots `flyingrobots/geordi#9`. Artifact hash `3193e7a88675d061`. Regenerate with `taskalisk.py --from-github [--root <ref>] --emit-roadmap`.

## DAG Structural Health

| Metric | Value |
| --- | --- |
| Open nodes | 7 |
| Reduced edges (raw) | 4 (4) |
| Edge density | 0.1905 (in band 0.01–0.50) |
| Max parallel width | 3 |
| Critical path (3) | partner/lib#1 → flyingrobots/geordi#1 → flyingrobots/geordi#2 |
| Isolated nodes | 0 |
| Containers excluded | flyingrobots/geordi#9 |

## Ranked Open Frontier (Wave 0)

| Rank | Score | Issue | Title | Status | Unblocks | Depth | Resources | Directly unlocks |
| ---: | ---: | --- | --- | --- | ---: | ---: | --- | --- |
| 1 | 231 | [partner/lib#1](https://github.com/partner/lib/issues/1) | (title not recorded) | open | 2 | 3 | — | flyingrobots/geordi#1 |
| 2 | 121 | [flyingrobots/bunny#110](https://github.com/flyingrobots/bunny/issues/110) | (title not recorded) | blocked | 1 | 2 | — | flyingrobots/geordi#110 |
| 3 | 121 | [flyingrobots/echo#5](https://github.com/flyingrobots/echo/issues/5) | (title not recorded) | open | 1 | 2 | — | flyingrobots/echo#6 |

### Conflict-Free git-locks Batch

- [partner/lib#1](https://github.com/partner/lib/issues/1) (title not recorded) — no resources
- [flyingrobots/echo#5](https://github.com/flyingrobots/echo/issues/5) (title not recorded) — no resources

## Task Checklist by Wave

### Wave 0

- [ ] [partner/lib#1](https://github.com/partner/lib/issues/1) (title not recorded) (open)
- [ ] [flyingrobots/bunny#110](https://github.com/flyingrobots/bunny/issues/110) (title not recorded) (blocked)
- [ ] [flyingrobots/echo#5](https://github.com/flyingrobots/echo/issues/5) (title not recorded) (open)

### Wave 1

- [ ] [flyingrobots/geordi#1](https://github.com/flyingrobots/geordi/issues/1) (title not recorded) (open)
- [ ] [flyingrobots/echo#6](https://github.com/flyingrobots/echo/issues/6) (title not recorded) (open)
- [ ] [flyingrobots/geordi#110](https://github.com/flyingrobots/geordi/issues/110) (title not recorded) (open)

### Wave 2

- [ ] [flyingrobots/geordi#2](https://github.com/flyingrobots/geordi/issues/2) (title not recorded) (open)

## Task Checklist by Workstream (`area:*`)

### feature

- [ ] [flyingrobots/echo#5](https://github.com/flyingrobots/echo/issues/5) (title not recorded)
- [ ] [flyingrobots/echo#6](https://github.com/flyingrobots/echo/issues/6) (title not recorded)
- [ ] [flyingrobots/geordi#1](https://github.com/flyingrobots/geordi/issues/1) (title not recorded)
- [ ] [flyingrobots/geordi#2](https://github.com/flyingrobots/geordi/issues/2) (title not recorded)
- [ ] [flyingrobots/geordi#110](https://github.com/flyingrobots/geordi/issues/110) (title not recorded)
- [ ] [partner/lib#1](https://github.com/partner/lib/issues/1) (title not recorded)

### unassigned

- [ ] [flyingrobots/bunny#110](https://github.com/flyingrobots/bunny/issues/110) (title not recorded)

## Transitively-Reduced Dependency DAG

```mermaid
flowchart TD
  subgraph Wave0["Wave 0: Open Frontier (Zero Incomplete Parents)"]
    N_partner_lib_1["partner/lib#1: (title not recorded)"]
    N_flyingrobots_bunny_110["flyingrobots/bunny#110: (title not recorded)"]
    N_flyingrobots_echo_5["flyingrobots/echo#5: (title not recorded)"]
  end
  subgraph Wave1["Wave 1"]
    N_flyingrobots_geordi_1["flyingrobots/geordi#1: (title not recorded)"]
    N_flyingrobots_echo_6["flyingrobots/echo#6: (title not recorded)"]
    N_flyingrobots_geordi_110["flyingrobots/geordi#110: (title not recorded)"]
  end
  subgraph Wave2["Wave 2"]
    N_flyingrobots_geordi_2["flyingrobots/geordi#2: (title not recorded)"]
  end
  N_partner_lib_1 --> N_flyingrobots_geordi_1
  N_flyingrobots_bunny_110 --> N_flyingrobots_geordi_110
  N_flyingrobots_echo_5 --> N_flyingrobots_echo_6
  N_flyingrobots_geordi_1 --> N_flyingrobots_geordi_2
```

## Prerequisite Edge Accounting

| Blocker | Blocked | Evidence |
| --- | --- | --- |
| flyingrobots/bunny#110 | flyingrobots/geordi#110 | frontmatter: flyingrobots/geordi#110 .blocked_by flyingrobots/bunny#110 |
| flyingrobots/echo#5 | flyingrobots/echo#6 | frontmatter: flyingrobots/echo#6 .blocked_by flyingrobots/echo#5 |
| flyingrobots/geordi#1 | flyingrobots/geordi#2 | frontmatter: flyingrobots/geordi#2 .blocked_by flyingrobots/geordi#1 |
| partner/lib#1 | flyingrobots/geordi#1 | frontmatter: flyingrobots/geordi#1 .blocked_by partner/lib#1 |

<!-- END GENERATED ISSUE DAG -->