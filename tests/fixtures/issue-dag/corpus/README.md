# Conformance corpus for `issue-dag/2` and `issue-dag-planning/2`

Status: accepted. This document is normative for the layout of the corpus,
the form of its cases and its digest. The rules the cases test are stated in
the [format](../formats/issue-dag-2.md), the [planning
profile](../profiles/issue-dag-planning-2.md) and the [version
policy](../versions.md); a case is evidence for those statements and never
the only definition of a rule (rule A9).

Only statements with a label such as **CC3** are normative. Everything else
is informative. The key words MUST, MUST NOT, SHOULD and MAY are used as in
RFC 2119 and RFC 8174 when they appear in capitals.

## Kinds of case

- A **normative** case states the result that the cited rules give for its
  input. The result is derived from the rule text, not from running an
  implementation.
- A **characterisation** case states what the reference implementation, the
  Python Taskalisk compiler, computes for its input. It detects a change in
  that implementation. It is not a statement of the rules.

Where the Python and a normative case disagree, the normative case records
the disagreement and its classification, and a characterisation case with
the same input, named `<name>--python`, records what the Python computes.

## Layout

**CC1. Directories.** The corpus is the directory `corpus/` of this
repository. Its cases are in `corpus/cases/document/<name>/` and
`corpus/cases/graph/<name>/`. A case's identifier is `<level>/<name>`, where
the level is `document` or `graph`.

**CC2. Files of a case.** Every case directory holds exactly three files, each
a JSON value in UTF-8:

- `case.json`, an object with the members `id`, `level`, `kind`
  (`normative` or `characterisation`), `title`, `cites` (a list of rule
  labels), `source` (where the input comes from), and optionally
  `disagreement` and `normative_case`;
- the input: for a document case `input.json`, an object with the members
  `body`, the issue body, and `address`, the reference of the issue that
  holds it; for a graph case `bundle.json`, an [observation
  bundle](bundle.md);
- `expected.json`, the expected result (CC5 and CC6).

**CC3. Citations.** A normative case cites at least one rule. Every label a
case cites, or names in its expected result, is the label of a normative
statement of this repository.

**CC4. Disagreements.** A normative case whose expected result differs from
the Python's has a `disagreement` member: an object with `classification`,
one of `legacy` (intended legacy behaviour: the rule changes to match),
`defect` (the Python is wrong) or `compatibility-exception` (an accepted
deviation, with its scope in `note`), `difference`, the number of the
difference in [the differences note](../notes/python-differences.md), and
`note`. The classification is the one the note gives that difference. A
normative case without the member agrees with the Python. A characterisation
case records a disagreement only as the twin of a normative case, named in
`normative_case`.

## Expected results

**CC5. Document cases.** The expected result of a document case is an object
whose `result` is one of:

- `no-document`: the body has no frontmatter block (format rule C3);
- `valid`, with `record`, the decoded record of format rule M4, and
  `warnings`, the labels of its warnings (V10);
- `invalid`, with `violations`, the labels of the rules the document fails,
  each once, in ascending order;
- `error`, with `error`, the kind of failure, in characterisation cases only:
  the implementation produced no judgement.

A record is an object with the members of M4's table. A reference is written
in canonical form; an absent value is null; `holds` is written as a list in
ascending order; a meter claim is written `[name, slots]`.

**CC6. Graph cases.** The expected result of a graph case is an object whose
`outcome` is one of `planned`, `invalid`, `incomplete` and `rejected`
(profile rule F1), or `error` in characterisation cases only. It may also
hold:

- `findings`: the violations, unknown prerequisites, cyclic nodes and
  warnings of the run, each `{"subject", "rule"}` with `concerns` when the
  rule concerns a reference: the issue that receives it, the label, and the
  reference (profile rule F5). They form a set;
- `nodes`: each node, `{"id", "complete", "opaque", "untrusted"}`, with
  `status` (rule S2) for an open node;
- `containers`, each with its `children` (rule W1); `unmodeled` and
  `untrusted`, lists of references; `untrusted_pull_requests`, a list of
  numbers;
- `edges`: each `{"from", "to", "status"}`, where `status` is `open` for an
  edge of the graph and `satisfied` for a completed prerequisite (rule G3);
  `redundant` and `not_planned`, lists of `{"from", "to"}`;
- `ready`: the ready set in rank order (rules Q1 and K6); `scores`, from node
  to score (K5); `waves` (K7); `critical_path` (K8);
- `batch`, in order of selection; `skipped`, each `{"id", "reason"}` with
  `semaphores` when the reason is `semaphore full`; `unknown_capacity` (B3).

An incomplete or rejected run has only `outcome` (rule F2).

**CC7. Labels.** The labels in `violations`, `warnings` and `findings` are
the ones format rule V12 gives a document's violations and warnings, and the
findings of a run, with their subjects and the references they concern, are
the ones profile rule F5 states. The corpus defines no label of its own.

**CC8. Comparison.** A characterisation case passes when the
implementation's result equals the expected result. A normative case passes
when every member of the expected result equals the implementation's; a
member that the expected result does not hold is not asserted. An invalid
run's graph is not asserted by normative cases (rule F3).

## Digest

**CD1. Digest.** The corpus digest is `sha256:` followed by the lower-case
hexadecimal SHA-256 of the concatenation, over every regular file under
`corpus/` except `corpus/DIGEST`, in ascending order of the UTF-8 bytes of
its path relative to `corpus/` (with `/` as the separator), of: the length
of the path in bytes as an unsigned 64-bit big-endian integer, the path, the
length of the file in bytes as an unsigned 64-bit big-endian integer, and the
file's bytes. `corpus/DIGEST` holds the digest and a line end. The digest is
recorded beside the format and the profile in the version table and is not
part of their identity (rule N4).

## Producing and checking the corpus

*Informative.* The cases are generated and checked by Taskalisk's
`scripts/corpus/` (`flyingrobots/taskalisk#26`):

```sh
python3 scripts/corpus/generate.py <issue-dag checkout> --vendor tests/fixtures/issue-dag
python3 scripts/corpus/check.py <issue-dag checkout>
python3 scripts/corpus/digest.py <issue-dag checkout>/corpus
```

The generator writes normative cases from their definitions and runs the
Python compiler offline for the characterisation cases: the parser and
validator for document cases, and discovery and compile, with every GitHub
call answered from the bundle, for graph cases. The checker runs the Python
again on every case, checks citations, classifications and bundles, and
checks the digest. Taskalisk's offline test suite runs the checker on its
vendored copy.

The characterisation cases come from the census of 2026-11-12, one body per
shape, from the inputs of the normative cases the Python disagrees with, and
from the backlogs of the Python's own offline tests and golden scenarios.
Edge edits are not covered: the corpus has no case for the [edge-edit
contract](../contracts/edge-edit.md).
