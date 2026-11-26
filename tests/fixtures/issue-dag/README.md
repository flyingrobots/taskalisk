# issue-dag

issue-dag is a format for dependency frontmatter in GitHub issue bodies, with
planning profiles that turn a set of such issues into a graph of work. This
repository holds the specification. It holds no implementation: two
implementations can be checked against one definition that neither owns.

A document is the first fenced `yaml` block of an issue body:

````markdown
```yaml
.dag: issue-dag/2
.id: flyingrobots/geordi#81
.kind: task
.type: feature
.blocked_by: [flyingrobots/geordi#78, flyingrobots/bunny#199]
.size_hours: 2
```
````

It says that `flyingrobots/geordi#81` is a feature task, and that two other
issues must be complete before it is correct.

## Documents

| Document | Read it to |
| --- | --- |
| [Format `issue-dag/2`](formats/issue-dag-2.md) | Decide whether an issue body is a valid document, and what it decodes to |
| [Planning profile `issue-dag-planning/2`](profiles/issue-dag-planning-2.md) | Compute the graph, the ready set, the ranking and the batch from a set of documents and their issues' state |
| [Versions and compatibility](versions.md) | Find the accepted and retired versions, and the rules for adding a version or claiming two are compatible |
| [Edge edit contract](contracts/edge-edit.md) | Change a `.blocked_by` list on GitHub without losing a concurrent edit unawares |
| [Typepack sketch `issue-dag@2`](typepacks/issue-dag@2/) | See the shape and laws as GraphQL SDL and weslaw (unvalidated) |
| [Census of frontmatter shapes, 2026-11-12](evidence/2026-11-12-frontmatter-shapes.md) | See every shape of block in use and the format's verdict on each |
| [Differences from the Python compiler](notes/python-differences.md) | See where the reference implementation and this specification disagree, and how each difference is classified |
| [Conformance corpus](corpus/README.md) | Test an implementation against cases for the format and the profile |
| [Observation bundle](corpus/bundle.md) | Record the complete input of a planning run, so that the plan can be computed again offline |

## Status

`issue-dag/2` and `issue-dag-planning/2` are accepted. Their conformance
corpus is in [`corpus/`](corpus/README.md), built by
`flyingrobots/taskalisk#26`; its digest is recorded in the [version
table](versions.md). Version 3 is planned in `flyingrobots/taskalisk#35` to
`#37`.

The decision to keep the specification here, apart from any tool, is
recorded in `flyingrobots/taskalisk`,
`docs/decisions/0001-rust-issue-dag-contract.md`.

## Changing the specification

A change to the version table, a format or a profile is a pull request to
this repository, reviewed by its maintainers ([versions.md](versions.md),
rule P5). Every rule a conformance case tests has a normative statement here
(rule A9); a case never defines a rule on its own.
