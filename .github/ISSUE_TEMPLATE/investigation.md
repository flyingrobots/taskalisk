---
name: Investigation
about: "Use when a system matters but we do not yet know what questions to ask about it."
labels: lane:inbox, type:spike
---

```yaml
.dag: issue-dag/2
.id: flyingrobots/taskalisk#NEW
.kind: task
.type: investigation
.blocked_by: []
.size_hours: 2
```

# Investigation

```text
You are the investigator for this issue. Read all sections of this issue.
Examine the area in section 2 at the locations in section 2b.
Stop when the time box in section 2c ends.
Record each finding in section 2d. Write one line for each finding.
File one typed issue for each finding. Write its number next to the finding.
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

## 2. What we do not understand
The area, not a question. If you have one question, file Research instead.
## 2b. Where to look
Surfaces, repositories, dashboards, people.
## 2c. Time box
## 2d. Findings
Empty at filing. One line per finding, each with the card it became.

## 3. Why now
## 4. Risks
## 5. Definition of Done
The map exists and every finding has a typed card.
## 6. Stakeholders
## 7. Related Issues
