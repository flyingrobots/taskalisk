---
name: Spike
about: "Use to test an approach with throwaway code inside a time box."
labels: lane:inbox, type:spike
---

```yaml
.dag: issue-dag/2
.id: flyingrobots/taskalisk#NEW
.kind: task
.type: spike
.blocked_by: []
.size_hours: 2
```

# Spike

```text
You are the engineer for this issue. Read all sections of this issue.
Test only the approach in section 2. Stop when the time box in section 2e ends.
Compare the result with the conditions in sections 2b and 2c.
Record adopt or reject, and the reasons, in section 2f.
Delete the throwaway code that section 2d names. Do not merge it.
Make sure that each item under Acceptance is true.
Read AGENTS.md and the project's code conventions before you change code.
Run the project's checks as AGENTS.md or the README gives them. Do not use --no-verify.
Open a draft pull request. Link this issue. Write progress comments on the pull request.
Make the pull request ready only when every item under Acceptance and in the Definition of Done is true and CI passes.
```

<!--
issue-dag/2 frontmatter (Taskalisk): after GitHub assigns the number, replace NEW in `.id` with it; a block
whose `.id` does not name the issue fails. Every reference is owner/repo#N, never a bare #N. List each
prerequisite issue in `.blocked_by` and explain it under Prerequisites. Above 8 hours is probably two tasks.
Write "none" or "not applicable, because X" instead of padding a section.
-->

## Outcome
One sentence, with one subject and one verb. If it needs "and", it is two issues.

## Scope
What the pull request contains.

## Out of scope
What a reader might expect that this leaves out, and where that work lives.

## Prerequisites
Each `.blocked_by` entry, with the reason it must close first.
- [ ]

## Safe intermediate state
What the default branch is like after this merges and before its dependents do.

## Acceptance
Exact, observable results.
- [ ]

## 1. Background Context

## 2. The approach being tested
## 2b. What would make us adopt it
## 2c. What would make us reject it
## 2d. What gets deleted afterwards
The code this produces is throwaway. Say so here.
## 2e. Time box
## 2f. Findings

## 3. Why now
## 4. Risks
## 5. Definition of Done
Adopt or reject, recorded, and the throwaway deleted.
## 6. Stakeholders
## 7. Related Issues
