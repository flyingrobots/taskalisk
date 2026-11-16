# Flat nine-section card template

The plain version every card carries. The typed templates in this folder refine the middle of it by card type. There is deliberately no effort or estimate section; sizing belongs to Scope (and to Blast radius for a Bug).

```markdown
## 1. Background Context
What this concerns.

## 2. Problem Description
What is broken or missing.

## 3. Proposed Solution
How to fix it.

## 4. Prerequisites
Before we start, these must be true.
- [ ]

## 5. Scope
In:
Out:

## 6. Acceptance Criteria
What must be true before this is considered finished.

## 7. Definition of Done
How to know when to stop.

## 8. Test Plan
Golden:
Edges:
Known failure modes:
Fuzz and stress:

## 9. Stakeholders
Named people or teams who care about this issue, and why.
```

Notes:
- Acceptance Criteria and Definition of Done are different: the first is what the result must satisfy, the second is the signal to stop, usually including recording the result.
- Write "none" or "not applicable, because X" instead of padding a section.
- Stakeholders names people where the record supports a name, and says why each cares.
