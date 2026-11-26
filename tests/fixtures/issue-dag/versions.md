# Versions and compatibility

Status: accepted. This document is normative. It states how issue-dag
versions are declared, accepted and retired, how a change between two versions
is judged, and in what order readers and documents move to a new version.

Only statements with a label such as **P3** are normative. Everything else,
including blocks marked *Commentary*, is informative. The key words MUST,
MUST NOT, SHOULD and MAY are used as in RFC 2119 and RFC 8174 when they
appear in capitals.

## Version table

**P5.** The accepted and retired sets are the ones recorded in this table.
They change only through a pull request to this repository that its
maintainers have reviewed.

### Formats

| Format | Typepack | Status | Definition | Retirement |
| --- | --- | --- | --- | --- |
| `issue-dag/1` | none recorded | Retired | Not specified here | Its references could be repository-relative (`#N`), and a transferred issue then makes a reference name another issue. Migration: write every reference as `owner/repo#N` and set `.dag: issue-dag/2`. |
| `issue-dag/2` | `issue-dag@2` | Accepted | [formats/issue-dag-2.md](formats/issue-dag-2.md) | |

### Planning profiles

| Profile | Supports | Status | Definition |
| --- | --- | --- | --- |
| `issue-dag-planning/2` | `issue-dag/2` | Accepted | [profiles/issue-dag-planning-2.md](profiles/issue-dag-planning-2.md) |

### Conformance corpus

| Corpus | Evidence for | Digest |
| --- | --- | --- |
| [`corpus/`](corpus/README.md) | `issue-dag/2`, `issue-dag-planning/2` | `sha256:015ae95e2e611ee70b75d22f9a6c99396bf2e9f7139c2e68502aad475c97940d` |

The digest is computed as [corpus rule CD1](corpus/README.md#digest) states
and is also held in `corpus/DIGEST`. It is recorded beside the format and the
profile and is not part of their identity (N4).

Identities (the digests of section 4) are not yet assigned; the manifest
format that fixes their encoding is later work.

## 1. Units

**U1.** A *typepack* is a named, versioned shape with its laws and a link to
the typepack of the preceding version.

**U2.** A *format* is a typepack, a carrier grammar and a key binding. A
format's name is `issue-dag/N`; its typepack is `issue-dag@N`.

**U3.** A *planning profile* is a named, versioned set of graph rules: edge
satisfaction, the cross-document rules, resource scope and conflict,
deferral, completion policy, ranking, batch selection and the consequence of
each lifecycle finding. A profile names the formats it supports.

**U4.** A *plan* is judged under exactly one profile. Two plans of the same
documents under different profiles may differ.

## 2. Version policy

A version `n` of the format defines a set of format keys `K(n)`, a validity
predicate `V(n)` and a meaning function `M(n)` from valid documents to records.

**P1.** A document is judged under the version it declares in `.dag`.

**P2.** A format key outside `K(ver(d))` is a violation.

**P3.** A conforming reader accepts every format in the accepted set of the
version table. It rejects a document that declares a retired format with a
violation that names the migration, and rejects a document that declares any
other unknown format.

**P4.** A format is retired only for a hazard: some document under it has a
meaning that depends on context the document does not carry. A meaning that
depends on observations a reader gathers and records, such as issue states,
is not a hazard.

**P5** is stated with the version table above.

**P6.** A document MAY declare version `n` only after every reader that plans
its repository accepts `n`.

**P7. Version dispatch.** Every format version keeps the location of the
frontmatter block (format rules C1 to C3) and the line grammar of `.dag`
(rules C5 to C9), so that a reader can find the declared version before it
knows the rest of the version's grammar.

**P8. Mixed graphs.** A graph MAY contain documents of several accepted
versions. An edge joins two references, not two documents of one version.

> *Commentary.* P2 keeps the protection against typing errors: an unknown key
> still fails, but the allowed keys follow the declared version, so adding a
> key no longer forces every existing issue to be rewritten. A rewrite is not
> free: each edit lengthens the edit history that the trust gate inspects and
> changes the body hash an execution approval is bound to. P4 is why
> `issue-dag/1` was rightly retired. Whether a given meaning is a hazard is a
> judgement; this policy gives the one example and no procedure.

## 3. Release rules

**R1.** Before documents in a repository declare a new version, every reader
in normal planning use for that repository accepts the version. A reader that
does not is upgraded or withdrawn from that use first.

**R2.** A recovery reader is kept outside normal planning use. It accepts
every version in the complete input closure of its repair plan: the repair
issues, their prerequisites, the issues reached through containers, and the
format and profile definitions they need.

> *Commentary.* A tool that plans its own repair can lock itself out: the
> running reader cannot read the documents that plan the fix. P3 does not
> prevent this, because it gives a newer reader backward compatibility, which
> is the wrong direction. R1 is P6 stated from the release side. R2 covers the
> case where the reader in use stops working; keeping an older binary is not
> enough once the backlog has moved past the versions it reads.

## 4. Identities

**N1.** The identity of a typepack is a digest over its name, its version,
the digest of its shape, the digest of its laws, the identity of its
predecessor or a marker for none, and the identifiers of the codecs that give
those digests their meaning. The encoding begins with a tag that names the
kind of object.

**N2.** The identity of a planning profile has the same form, over its name,
its version, the canonical text of its rules and its predecessor.

**N3.** The name and version of the program that computed an identity are
provenance. They are recorded beside the identity and are not part of it.

**N4.** The conformance corpus is evidence for a format and a profile. Its
digest is recorded beside them and is not part of their identity.

## 5. Compatibility claims

<a id="compatibility-claims"></a>

A change between two versions can preserve or alter six observables.

| Observable | Question |
| --- | --- |
| O1, acceptance | Is every old document still valid on its own? |
| O2, decoded meaning | Does it decode to an equal record? |
| O3, structure | Does it declare the same prerequisites, children and resources? |
| O4, readiness | Are the same tasks eligible? |
| O5, ranking | Do they keep their order? |
| O6, batch | Does the same set receive resources? |

**A1.** O1 is local acceptance: whether one document, with its carrier
bytes, is valid without reference to any other document or observation.
Cross-document rules belong to the planning profile.

**A2.** A compatibility claim states a direction, a purpose and the
observables it preserves. A claim about issue-body bytes names the two
formats it compares. A claim about O4 to O6 also names the two planning
profiles it compares.

**A3. Additive.** Version `n+1` is *additive* over `n` when, for every
document valid under `n`, relabelling it to `n+1` preserves O1 and O2. For
this comparison O2 compares the two decoded records with their `version`
fields removed: relabelling changes that field by definition, and every other
field must be equal. O3 then follows, because structure is part of the
record. The claim is made in one direction only: a reader of `n` rejects a
document of `n+1` by its version.

**A4. Verdicts.** A comparison yields one of three verdicts for a stated
claim:

- *compatible*: the evidence supports the claim;
- *incompatible*: a witness shows that the claim fails;
- *unknown*: neither; the comparison needs review.

A typepack with no predecessor has no comparison. That is recorded as
*first*, which is not a verdict.

**A5. Checks for additivity.** Four checks contribute:

1. *Shape*: the schema delta between the two shapes, within the shape dialect
   (A6). Outside the dialect the shape check is *unknown*.
2. *Laws*: each event of the law diff is classified through a table that this
   repository owns. An event the table does not classify is *unknown*.
3. *Behaviour*: a copy of every document-level conformance case of version
   `n` (a case that judges one body: its acceptance and its decoded record)
   whose body is valid under `n`, with its declaration relabelled to `n+1`,
   is accepted and decodes, compared as A3 says, to the record the case
   expects, when the new reader dispatches it as `n+1` (P1). A case whose
   body is invalid under `n` is not relabelled: an additive version may
   accept it, which A3 allows. Cases that judge a plan are compared under the
   planning profiles a claim names (A2), not here. The unchanged cases of
   version `n` are run separately, as the check that the new reader still
   reads `n`; that check is not evidence for additivity.
4. *Carrier, binding and value rules*: the carrier grammar, the key binding
   and the value rules of `n+1` (how each value is decoded, the decoded value
   of an absent key, and the constraints on each scalar, such as integer
   bounds and the form of a reference) are each unchanged from `n`, or a
   comparison of the two shows that every body accepted under `n` is accepted
   under `n+1` and decodes to the same record, compared as A3 says. A finite
   corpus cannot show this; the comparison is of the rules themselves.

The verdict is *incompatible* when any check produces a witness. It is
*compatible* only when the shape is non-breaking within the dialect, every
law event is classified as non-restricting, every relabelled case passes,
and the carrier, the binding and the value rules are unchanged or shown to
accept and decode as before. Otherwise it is *unknown*.

**A6. Shape dialect.** A typepack shape uses only GraphQL `input` types,
custom scalars, enums, lists and nullability. It uses no default values and
no directives on fields. The dialect widens only when the schema delta
handles the new feature and has tests for it.

**A7. External verifiers.** A law that points to an external verifier names
it by a pinned identity. A verdict that depends on an unpinned verifier is
*unknown*.

**A8. Verdicts are readings.** A verdict is keyed by the two identities it
compares, the claim's observables, the evaluator and its version, and the
digest of the corpus it was checked against. A newer evaluator adds a verdict
beside the old one; it does not replace it.

**A9. Normative source.** Every rule a conformance case tests has a
normative statement in this repository. A case is evidence for a statement
and is never the only definition of a rule.

> *Commentary.* The shape delta sees only the shape. Laws can change
> acceptance, so within its dialect the delta may decide only shape-level
> acceptance; local acceptance needs the law check as well, and acceptance of
> bytes needs the carrier and the binding held fixed or compared. A passing
> finite corpus supports a claim and never proves it. Wesley's schema delta
> does not compare the default values of input fields, which is why A6 bans
> defaults.
