---
name: Feature
about: "Use when the end state is known and only the work remains."
labels: lane:inbox, type:enhancement
---

```yaml
.dag: issue-dag/2
.id: OWNER/REPO#NEW
.kind: task
.type: feature
.blocked_by: []
.size_hours: 2
```

# Feature

```text
You are the engineer for this issue. Read all sections of this issue.
Write tests from section 2c (Test Plan) first. Make sure that they fail before you write the code.
Write the code from section 2b. Make sure that all tests pass.
Make sure that each item under Acceptance is true.
Do not change anything that Out of scope names.
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

## 2. Problem Description
## 2b. Proposed Solution
One line each for the alternatives considered and rejected.
## 2c. Test Plan
Golden:
Edges:
Known failure modes:
Fuzz and stress:

## 3. Why now
## 4. Risks
## 5. Definition of Done
## 6. Stakeholders
## 7. Related Issues
