---
name: Research
about: "Use when there is one answerable question and a decision waits on the answer."
labels: lane:inbox, type:spike
---

```yaml
.dag: issue-dag/2
.id: OWNER/REPO#NEW
.kind: task
.type: research
.blocked_by: []
.size_hours: 2
```

# Research

```text
You are the researcher for this issue. Read all sections of this issue.
Answer only the question in section 2.
Use the method in section 2c. Obey the limits in section 2d.
Record the value, the command, and the time in section 2f.
If you cannot answer the question, record why in section 2f.
Make sure that each item under Acceptance is true.
Do not change code.
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

## 2. The Question
One sentence, answerable.
## 2b. What decision waits on it
If nothing does, do not file this.
## 2c. What would settle it
The observation, the method, and where the data lives.
## 2d. Aperture
What this cannot see, so a negative result is not read as a positive.
## 2e. Possible answers and what each implies
Written before looking.
## 2f. Evidence
Empty at filing. The value, the command that produced it, the timestamp.

## 3. Why now
## 4. Risks
## 5. Definition of Done
An answer under Evidence, or a declared unanswerable-because.
## 6. Stakeholders
## 7. Related Issues
