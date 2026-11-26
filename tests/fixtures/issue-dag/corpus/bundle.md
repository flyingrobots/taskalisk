# Observation bundle `issue-dag-observations/1`

Status: accepted. This document is normative. It defines the observation
bundle: the complete input of one planning run, so that the plan can be
computed again offline, from the bundle alone, by any planner. The graph
cases of the [conformance corpus](README.md) take a bundle as their input.

Only statements with a label such as **OB4** are normative. Everything else,
including examples and blocks marked *Commentary*, is informative. The key
words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119 and RFC 8174 when
they appear in capitals.

A bundle records what the run observed, not what it concluded. It holds the
run parameters of the [planning profile](../profiles/issue-dag-planning-2.md)
(rule I1) and every observation the profile reads (rules I3 and I4), and the
observations a trust policy reads to make the admission decisions of rule I3.

## Example

```json
{
  "bundle": "issue-dag-observations/1",
  "format": "issue-dag/2",
  "profile": "issue-dag-planning/2",
  "parameters": {
    "home": "o/r",
    "roots": ["o/r#1"],
    "read_scope": {"owners": ["o"], "repositories": []},
    "trust": {"policy": "taskalisk/threat-model", "logins": ["dev"], "codeowners": false},
    "capacities": {"gpu": 2}
  },
  "observations": {
    "home_open_pull_requests": {"value": []},
    "issues": {
      "o/r#1": {"value": {
        "address": "o/r#1", "pull_request": false, "state": "open", "state_reason": null,
        "author": {"login": "o", "type": "User"}, "author_association": "OWNER",
        "body": {"value": {"text": "```yaml\n.dag: issue-dag/2\n...", "editors": [{"login": "o", "type": "User"}]}}
      }},
      "o/r#2": {"unavailable": "HTTP 502 from the issues endpoint"}
    },
    "permissions": {"o/r": {"carol": {"value": null}}}
  }
}
```

A planner given this bundle reads `o/r#1`; if its document names `o/r#2`, the
run is *incomplete* (profile rule F1), because that observation is
unavailable.

## 1. The bundle

**OB1. Container and version.** A bundle is one JSON value (RFC 8259) in
UTF-8: an object with exactly the members `bundle`, `format`, `profile`,
`parameters` and `observations`. The value of `bundle` is the string
`issue-dag-observations/1`. A reader MUST reject a bundle with another value
or with another set of members. No object of a bundle, at any depth, gives a
member twice: RFC 8259 leaves the meaning of such an object to the reader,
so a reader MUST reject a bundle that holds one rather than keep either
value.

**OB2. Versions in use.** `format` and `profile` name the format and the
planning profile of the run, as the [version table](../versions.md) names
them: here `issue-dag/2` and `issue-dag-planning/2`.

**OB3. Run parameters.** `parameters` is an object with exactly these
members, which are the run parameters of profile rule I1:

- `home`: the home repository `H`, as `owner/repo` in canonical form (OB13);
- `roots`: the root references as they were given, a list of strings, empty
  when the run has none. They are recorded unvalidated, so a run that rule I2
  rejects can be recorded;
- `read_scope`: an object with the members `owners` and `repositories`, each
  a list in canonical form. A repository is in the read scope when it is
  listed in `repositories` or its owner is listed in `owners`. The read scope
  MUST include `H`;
- `trust`: an object with the members `policy`, the name of the trust policy
  that makes the admission decisions, `logins`, the logins that policy trusts
  by name, and `codeowners`, true when that policy reads CODEOWNERS files.
  These are the trust parameters of profile rule I1. The policy
  `taskalisk/threat-model` is defined by the [admission
  policy](../profiles/admission.md), rules AD1 to AD10, and is the only one
  this specification defines. A bundle that names another policy is a valid
  bundle; its run is rejected (profile rule I2);
- `capacities`: an object from semaphore names to positive integers, possibly
  empty.

## 2. Observations

**OB4. Observation slots.** Each observation is held in a *slot*: an object
with exactly one member, either `value`, holding what was observed, or
`unavailable`, holding a non-empty string that says why the observation could
not be made. An observation that the planner could not make, or could not
show to be complete, is recorded as unavailable (profile rule I5). It is
never recorded as an empty value, and an observed empty value is never
recorded as unavailable.

**OB5. Missing slots.** A slot that a bundle does not hold was not recorded.
A reader that needs it MUST reject the bundle as incomplete evidence. It MUST
NOT read the missing slot as empty, and MUST NOT read it as unavailable: an
unavailable observation makes the run incomplete, a missing one makes the
bundle unusable.

**OB6. Home listing.** When `roots` is empty, `observations.home_open_issues`
is the slot of profile rule I4's listing: a list of the references, in
canonical form, of every open issue of `H` that is not a pull request, each
once. A listing that may have been truncated is unavailable. When `roots` is
not empty, the member is absent.

**OB7. Home pull requests.** `observations.home_open_pull_requests` is the
slot of the list of `H`'s open pull requests. Each item is an object with
exactly these members:

- `number`: its number;
- `repository`: `H`;
- `head_repository`: the repository of its head branch, or null when it was
  not observed;
- `cross_repository`: whether the head branch is in another repository, or
  null when it was not observed;
- `author`: an actor (OB9), or null for a deleted account;
- `draft`: a boolean, or an unavailable slot when the draft flag that was
  observed is not a boolean. The member is recorded for every item, even
  when no rule of the run reads it; profile rule I5 makes only its value
  unavailable without consequence, never the member absent;
- `closes`: the references, in canonical form, of the issues it closes.

**OB8. Issues.** `observations.issues` is an object whose members are keyed
by a reference in canonical form, as the run read it: the reference a root
or a document names, not the address it resolved to. A reference outside the
read scope is never read and is never a key. Each member is a slot whose
value is an object with these members, `body` optional, and no other:

- `address`: the reference of the issue's address now, in canonical form; it
  differs from the key when the issue was transferred;
- `pull_request`: true when the reference resolves to a pull request;
- `state`: `open` or `closed`;
- `state_reason`: the close reason as GitHub reports it, such as `completed`
  or `not_planned`, or null;
- `author`: an actor, or null for a deleted account;
- `author_association`: the author's association with the repository as
  GitHub reports it, such as `OWNER`, `MEMBER` or `NONE`, or null;
- `body`: a slot whose value is an object with the members `text`, the issue
  body, and `editors`, the actor of every edit of the body's edit history,
  the creation included, in order, with null for a deleted account. The two
  are observed together, so that the editors are those of that text. The
  member MAY be absent when the run does not read the body (OB14).

A reference that resolves to no issue that the planner can see is recorded as
unavailable (profile rule D10).

**OB9. Actors.** An actor is an object with exactly the members `login`, as
GitHub returns it, and `type`, the actor type GitHub reports, such as `User`
or `Bot`.

**OB10. Permissions.** `observations.permissions` is an object from a
repository, in canonical form, to an object from a login, in lower case, to a
slot. The value of the slot is the permission GitHub reports for that login
on that repository, such as `admin`, `maintain`, `write`, `triage` or `read`,
or null when the login is not a collaborator.

**OB11. CODEOWNERS.** When `parameters.trust.codeowners` is true,
`observations.codeowners` is an object from a repository, in canonical form,
to a slot whose value is an object with the members `path`, one of
`.github/CODEOWNERS`, `CODEOWNERS` and `docs/CODEOWNERS`, the first of them
that exists, and `text`, its content; or null when none exists. Otherwise the
member is absent.

**OB12. What a bundle does not hold.** Titles, URLs, labels, milestones,
comments, branch names and GitHub's issue relationships are not observations
of the profile, and a bundle does not hold them. A bundle holds no admission
decision: the planner makes it from the slots, under the policy that
`parameters.trust.policy` names.

**OB13. Canonical form.** Every reference and repository in a bundle is
written in canonical form (format rule L1): owner and repository in ASCII
lower case. Logins are compared without regard to ASCII case.

**OB14. Completeness.** A bundle MUST hold every slot that the run reads:
under the profile, and under the trust policy for the issues and pull
requests the run reads. It MAY hold slots that the run does not read.

**OB15. Observation members.** `observations` is an object whose members are
among `home_open_issues`, `home_open_pull_requests`, `issues`, `permissions`
and `codeowners`, the members OB6 to OB11 define. A reader MUST reject a
bundle whose `observations` holds any other member, rather than ignore it:
a misspelt slot would otherwise be read as a slot that was not recorded.

> *Commentary.* A bundle that OB1 or OB15 rejects is not a bundle, so no
> graph case of the corpus can hold one: a case's input is a bundle (corpus
> rule CC2) and its expected result is the outcome of a run (CC6). A bundle
> that lacks a slot its run reads breaks OB14 but is still a bundle: OB5
> makes it unusable, and a case can expect that (CC6, OB16). The corpus
> tooling still requires the home listing (OB6) in a run without roots, so
> no case lacks it; such a run would read no issue anyway.
>
> OB5 is what keeps a bundle honest. A recorder that forgets to
> record a lookup produces a bundle that a replay rejects, rather than one
> that silently answers *no pull requests* or *no editors*. A slot the run
> does not read, such as the body of an issue whose author is not trusted, can
> be kept or left out; keeping it costs nothing and lets a second trust policy
> be tried on the same evidence.
>
> The admission decision belongs to the trust policy that the bundle names.
> This specification defines one, `taskalisk/threat-model`, in the
> [admission policy](../profiles/admission.md) (profile rule I6), and every
> bundle of the corpus names it. A bundle carries the observations a policy
> reads and names the policy; a case whose expected plan depends on an
> admission decision depends on that policy too.

## 3. What a run reports

**OB16. Lookups that could not be made.** A run over a bundle reads every
slot that the rules reach before it ends. A slot that is missing (OB5) or
unavailable (OB4) leaves undecided only the decision that reads it: the run
does not read the slots that only that decision would lead to, and goes on
with every other lookup of discovery (profile rules D1, D2 and I4) and of
admission (I6), every editor of a body included (AD8). The draft flags that
profile rule S2 reads are reached only when every slot of discovery and
admission that the run reached holds a value, since S2 gives a status only
to a node of a graph and a run that cannot make a lookup has no graph (F2);
the run then reads every one of them. When the run reached a slot it could
not read, it reports exactly one:

1. When a slot it reached is missing, the bundle is unusable (OB5) and the
   run reports the least missing slot it reached. It reports no unavailable
   slot and has no outcome under profile rule F1.
2. Otherwise the run is *incomplete* (F1) and reports the least of the
   reasons (OB4) recorded in the unavailable slots it reached, as strings
   compared by their UTF-8 bytes.

A missing slot is identified by its path: the member names that lead to it
from `observations`, in canonical form (OB13), as corpus rule CC6 writes it,
such as `["issues", "o/r#2"]` or `["permissions", "o/r", "carol"]`. Paths
are compared member name by member name, each name by its UTF-8 bytes, and a
path that begins another comes before it. So the home pull requests come
before an issue, `o/r#10` before `o/r#2`, the body of `o/r#2`
(`["issues", "o/r#2", "value", "body"]`) before the issue `o/r#3`, and a
permission on `o/r` before any permission on `o/s`. Neither the order of the
roots, nor the order in which discovery visits references (D2), nor the
order of the nodes changes the slot a run reports.

> *Commentary.* A planner that stopped at the first lookup it could not make
> would report whichever slot the order of the roots put first. Reading on
> is what makes the report a function of the bundle. A missing slot comes
> first because it says the evidence is unusable, and an unavailable slot
> must not hide that. Ordering by path needs no list of kinds: it is the
> order of the bundle's own member names, and the path is what a case
> reports. Two unavailable slots with the same reason are not told apart,
> since the reason is what is reported.
