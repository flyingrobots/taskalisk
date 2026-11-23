---
name: Bug
about: "Use when there is a symptom and no known cause. No Proposed Solution at filing; Diagnosis is required before fix work starts."
labels: lane:inbox, type:bug
---

```yaml
.dag: issue-dag/2
.id: OWNER/REPO#NEW
.kind: task
.type: bug
.blocked_by: []
.size_hours: 2
```

# Bug

```text
You are the engineer for this issue. Read all sections of this issue.
Do not start a fix before section 2f (Diagnosis) is complete.
Reproduce the symptom in section 2c. Record the cause in section 2f.
Write a regression test. Make sure that it fails before the fix.
Fix the cause. Make sure that the test passes after the fix.
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

## 2. Observed
What happens now.
## 2b. Expected
What should happen instead.
## 2c. Reproduction
Steps, or: not reproduced, observed in production at <time> from <source>.
## 2d. Blast radius
Who is affected, as a population.
How many, with the query that produced the number, marked observed or estimated.
Since when.
Downstream: what consumed the wrong value.
## 2e. Hypothesis
What I think is happening, and the observation that would kill it.
## 2f. Diagnosis
Empty at filing. Required before any fix work starts.

## 3. Why now
## 4. Risks
## 5. Definition of Done
A regression test that fails before the fix and passes after it.
## 6. Stakeholders
## 7. Related Issues
