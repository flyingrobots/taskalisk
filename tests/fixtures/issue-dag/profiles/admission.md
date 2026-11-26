# Admission policy `taskalisk/threat-model`

Status: accepted. This document is normative. It defines the admission
policy that an [observation bundle](../corpus/bundle.md) names as
`taskalisk/threat-model`: how a planner decides, from the recorded
observations alone, whether an issue or a pull request is *admitted*. The
[planning profile](issue-dag-planning-2.md) reads that decision (rules I3,
I4, D6, D7, D8, S1, T1 and T2); this document is how it is made.

The rules state what the reference implementation, the Python Taskalisk
compiler, applies (`TrustPolicy` in `skills/taskalisk/scripts/taskalisk.py`),
and the policy stated in Taskalisk's threat model (`docs/threat-model.md`,
controls C1, C2, C4 and C18). Where the two differed, this document states the
policy, and [the reconciliation notes](../notes/python-differences.md) list
the difference. No rule differs from the Python. The threat model contradicted
itself once: C1 called a check that cannot be made *untrusted*, and also said
that any trust lookup that cannot run fails the run. The second governs
(AD10), as the Python does, and the threat model was corrected to say so.

Only statements with a label such as **AD4** are normative. Everything else,
including examples and blocks marked *Commentary*, is informative. The key
words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119 and RFC 8174 when
they appear in capitals.

## 1. Inputs

**AD1. Inputs.** An admission decision is a function of the run parameters
and the observations of a bundle, and of nothing else:

- the read scope, `parameters.read_scope` (bundle rule OB3);
- the allowlist, `parameters.trust.logins`;
- whether CODEOWNERS files are read, `parameters.trust.codeowners`;
- for an issue, its author, its author association and its body slot, which
  holds the body's editors (OB8);
- for a pull request, its author and `cross_repository` (OB7);
- the permissions (OB10) and the CODEOWNERS files (OB11) that the rules
  below read.

A planner MUST NOT use an observation that is not listed here, such as a
title, a label or a comment, to admit anything.

**AD2. Scope.** Only an issue whose repository is in the read scope is
judged. An issue outside it is never read (profile rule D3) and is never
admitted. A pull request is judged only in the home repository `H`, which
the read scope includes. Association, permission and CODEOWNERS count only
for the repository in which they were observed: a person trusted in one
repository is not, for that reason, trusted in another.

> *Commentary.* `OWNER` is true of anyone in their own repository. Scope is
> what keeps an attacker who owns `mallory/trap` from admitting
> `mallory/trap#1` (threat model, T06).

## 2. Identities

**AD3. Identities.** An actor's *identity* is a pair: whether it is a bot,
and its name in ASCII lower case. An actor is a bot when its `type` is
`Bot`, when its login ends in `[bot]`, or when its login begins with `app/`;
its name is then the login without that suffix or prefix. Every other actor
is a person, named by its login. Two actors are the same when their
identities are equal: logins compare without regard to ASCII case, and a bot
and a person never share an identity, even when their names are equal.

**AD4. Allowlist entries.** An entry of `parameters.trust.logins` that ends
in `[bot]` or begins with `app/` names the bot identity of the rest of the
entry; any other entry names the person identity of the entry. Entries
compare as identities (AD3).

> *Commentary.* `--trust x` trusts the person `x` and not the app `x`;
> `--trust x[bot]` trusts the app and not the person.

## 3. Judging one actor

**AD5. Trusted actor.** An actor `a` is judged in a repository `r` of the
read scope, with an author association `s` when `a` is an issue's author
and with none otherwise. The judgement is the first of these steps that
applies:

1. `a` is null (a deleted account): *not trusted*.
2. `a`'s identity is on the allowlist (AD4): *trusted*.
3. `a` is a bot: *not trusted*.
4. CODEOWNERS files are read and `a` is a person named in the CODEOWNERS of
   `r` (AD7): *trusted*.
5. `s` is `OWNER`: *trusted*.
6. `s` is present and is not `OWNER`, `MEMBER` or `COLLABORATOR`: *not
   trusted*.
7. The permission of `a` on `r` (AD6) is `admin`, `maintain` or `write`:
   *trusted*. Any other permission, and null (not a collaborator): *not
   trusted*.

Associations and permissions are compared exactly as recorded.

> *Commentary.* `MEMBER` and `COLLABORATOR` include read- and triage-level
> people, so they lead to the permission, never to trust by themselves. An
> association outside the three means GitHub reports no collaborator
> standing, so step 6 decides without a permission lookup (threat model, C1
> and C15). A stranger's issue then costs no lookup, except that when
> CODEOWNERS files are read, step 4 reads the repository's CODEOWNERS first. A bot is trusted only
> by name: neither association, nor permission, nor CODEOWNERS trusts it.

**AD6. Permission lookup.** The permission of `a` on `r` is the slot
`observations.permissions[r][l]`, where `l` is `a`'s login in lower case.
It is read only when step 7 of AD5 is reached.

**AD7. CODEOWNERS.** When `parameters.trust.codeowners` is true, the
CODEOWNERS of `r` is the slot `observations.codeowners[r]`, read only when
step 4 of AD5 is reached. A null value names nobody. Otherwise the persons
it names are found line by line. The text is split into lines at every
Unicode line break: LF, CR, CR LF, U+000B, U+000C, U+001C to U+001E, U+0085,
U+2028 and U+2029. The text of a line before its first `#` is split into
tokens at every run of these characters: U+0009 to U+000D, U+001C to
U+001F, U+0020, U+0085, U+00A0, U+1680, U+2000 to U+200A, U+2028, U+2029,
U+202F, U+205F and U+3000 (the Unicode `White_Space` characters and U+001C to
U+001F). Each token after the first
that begins with `@` is an owner, and its *name* is the rest of the token. A
name that contains `/` is a team; it is not expanded and trusts nobody. An
empty name, from a bare `@`, names nobody. Any other name names the person
with that login (AD3). A token that does not begin with `@`, such as an
e-mail address, names nobody. CODEOWNERS only adds trust; it never removes it, and it never
widens the scope (AD2).

> *Commentary.* The file is the one on the default branch, as bundle rule
> OB11 records it. Its value is that a ruleset can require code-owner review
> of changes to it (threat model, C18).

## 4. Decisions

**AD8. Issue admission.** An issue that discovery reads in a repository `r`
of the scope, and that is neither a pull request (profile rule D4) nor
transferred (D5), is judged as follows:

1. Its author is judged in `r` with its author association (AD5). If the
   author is not trusted, the issue is *not admitted*, and its body slot is
   not read.
2. Otherwise its body slot is read. Each editor in the body's edit history
   whose identity differs from the author's and from every editor before it
   is judged in `r` without an association. Every such editor is judged,
   even after one is not trusted.
3. The issue is *admitted* when every editor judged in step 2 is trusted, and
   *not admitted* otherwise.

The body of an admitted issue, the one the profile reads (I3, D7, D8), is
the text of that body slot.

**AD9. Pull-request admission.** Each open pull request of `H` that closes
at least one issue is judged. It is *admitted* when its `cross_repository`
is `false` and its author, judged in `H` without an association (AD5), is
trusted. When `cross_repository` is `true` or null (not observed), it is
*not admitted* and its author is not judged. A pull request that closes no
issue has no decision and reads nothing.

> *Commentary.* A fork's head branch is written by whoever owns the fork, so
> a pull request from a fork links nothing, whoever opened it (threat model,
> C4, T04a).

## 5. Completeness

**AD10. Unavailable lookups.** Every slot that AD5 to AD9 read is a required
observation of the run (profile rule I5). When one is unavailable, the
decision is not made and the run is *incomplete* (F1): the planner MUST
NOT read an unavailable lookup as *not trusted*, nor as *trusted*. A slot
that the rules do not reach, such as the permission of an allowlisted login,
of a bot, or of an author whose association decides at step 5 or 6, or the
body of an issue whose author is not trusted, is not required.

> *Commentary.* A silently untrusted collaborator would hide trusted work
> behind opaque blockers while the run reported success. Because every
> editor is judged (AD8, step 2), an unavailable permission of a later
> editor makes the run incomplete even when an earlier editor is already
> not trusted.
