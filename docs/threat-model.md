# Threat model and security policy

**Status**: Proposed on 2026-11-08; binding when the user accepts it, which
the merge of flyingrobots/taskalisk#16 records. Decisions the user has
already taken are marked *decided*. Covers the compiler as built and the
executor as planned in flyingrobots/taskalisk#9, #10, #13, #14 and #15, as if
all of them were implemented.

The policy sections ("must", "never") are binding on the script, on
`SKILL.md`, and on every executor issue. A control marked *implemented* has a
test. A control marked *planned* names the issue that must implement it; that
issue is not done until the control has a test. A control marked *policy*
binds operators and executor issues through review rather than through
code: C8 and C14 are owed by #13 (the runner enforces the sandbox, the
allowlist and the scoped token, and refuses to start without them), C17 by
every change to `docs/frontmatter-model.md`.

## 1. The execution path

1. **Compile.** The script lists the open issues of the home repository, fetches
   every issue their frontmatter references (across repositories), and builds
   the DAG from `.blocked_by`.
2. **Rank and batch.** Open tasks with zero open blockers form the frontier. An
   open PR that closes an issue marks the task *in flight* (+1000 priority).
   `.holds` and `.meters` shape a conflict-free batch.
3. **Select** (planned, #9). The executor takes the batch minus in-flight work.
4. **Prompt** (planned, #10). The executor builds a prompt from the issue body,
   the closed blockers and their PRs, the repository's agent instructions, the
   branch state and CI.
5. **Run** (planned, #13). A coding agent from the operator's settings runs on
   the operator's machine with the operator's `gh` credentials. It pushes a
   branch and opens a draft PR.
6. **Resume** (planned, #15). A draft PR without a live lease is "stalled"; the
   executor checks out its branch and continues it.
7. **Gate and merge** (planned, #14). Predicates from the operator's settings
   decide whether the PR merges; with `merge = true` the executor merges.

Every step after 2 turns text that came from GitHub into actions on the
operator's machine and in the operator's repositories.

## 2. Assets

| Asset | Why it matters |
| --- | --- |
| `main` of every repository in the closure | The executor produces merges. |
| The operator's machine | Agents run as the operator's user. Checkouts run hooks. |
| The operator's GitHub credentials | Agents call `gh` with them. |
| Graph integrity (edges, ranking, in-flight state) | Decides what runs first and what never runs. |
| Planner availability | The compiler fails closed; a forced failure stops planning. |
| Tracked outputs (`ROADMAP.md`) | Rendered in public repositories. |

## 3. Actors

| Actor | Can, on a public repository | Cannot |
| --- | --- | --- |
| Anonymous GitHub user | Open issues; edit their own issue body; comment anywhere; open PRs from a fork with `Closes owner/repo#N`; submit a PR review, including `APPROVED`; create a repository under any free name (slug squatting) | Label; edit others' bodies; set native relationships; push branches |
| Triage collaborator | All of the above plus labels and native relationships | Push |
| Write collaborator | Push branches; edit any issue body; open same-repository PRs | Change protected branches without review, if a ruleset says so |
| GitHub App or bot | Comment; review; set checks | Act outside its installation permissions |
| The coding agent | Everything the operator's credentials and machine allow | Tell instructions from data on its own |
| The operator | Settings, flags, keys | — |
| Network attacker | Only by breaking TLS; then also `git fetch` | — |

The agent is a confused deputy: it has the operator's authority and reads
attacker-influenced text. Every control below either keeps untrusted text away
from the agent or keeps the agent's authority small.

## 4. Trust boundaries

- **B1 GitHub content → script.** Issue bodies, titles, PR bodies, comments and
  reviews are attacker-influenced data.
- **B2 Script → agent prompt.** The prompt is built from B1 data.
- **B3 Agent → tools and GitHub.** Actions run with the operator's identity.
- **B4 Operator settings → script.** Agent commands, gate commands, trust lists.
- **B5 Repository checkout → script and agent.** Hooks, scripts, and the
  agent-instruction files (`CLAUDE.md`, `AGENTS.md`) of whatever branch is
  checked out.
- **B6 Network.** TLS to `api.github.com`.

Trust that matters is *per repository*. `authorAssociation: OWNER` is true of
anyone in their own repository. Association therefore counts only inside the
trusted repository scope (C2).

## 5. Threats

Severity is the worst outcome if nothing else stops it. "Where" names the
control and whether it exists.

| ID | Vector | Outcome | Severity | Where |
| --- | --- | --- | --- | --- |
| T01 | A stranger opens an issue with valid frontmatter in the home repository. It seeds discovery, has no blockers, tops the frontier, and the executor turns its body into a prompt. | Arbitrary instructions run with the operator's authority. | Critical | C1, C3 implemented; C7, C8 planned (#9, #10, #13) |
| T02 | A body edit of a trusted issue by an untrusted editor (a collaborator account that should not dispatch, a compromised account). | Same as T01 through a trusted-looking issue. | High | C1 covers every editor; C9 planned (#9) |
| T03 | A trusted issue quotes untrusted text: comments (anyone can comment), a fork PR description, pasted content. | Prompt injection through a trusted node. | High | C7, C8 planned (#10, #15); comments never enter a prompt unless their author is trusted, and then as data |
| T04a | A fork PR says `Closes owner/repo#N`. The task becomes *in flight*. | Ranking manipulation (+1000); or the task is frozen as "already in progress" and never dispatched. | High | C4 implemented |
| T04b | The planned resume (#15) treats that fork PR as a stalled task and checks out its branch. | Attacker hooks and scripts run in the worktree; attacker `CLAUDE.md` enters the prompt; attacker comments are context; the agent continues attacker work. | Critical | C4 implemented; C10, C11 planned (#15, #10) |
| T04c | The planned gate (#14) evaluates that adopted PR. CI on a fork PR runs the fork's workflow file; anyone can leave an `APPROVED` review. With `merge = true`, the executor merges. | Attacker code on `main`. | Critical | C4 implemented; C12, C13 planned (#14) |
| T05 | Many untrusted issues each list a trusted issue in `.blocked_by`. | The trusted issue's descendant count, and so its priority, is inflated. | Medium | C3: untrusted issues are not nodes and have no edges |
| T06 | A trusted issue references `owner-typo/repo#1` (squatted) or any repository outside ours. The attacker is OWNER there. | Attacker issue enters as a trusted node; it blocks or unblocks our tasks at will; its `.holds` block our batch. | High | C2 implemented |
| T07 | `.holds: [host/]` or large `.meters` on an untrusted node. | Batch denial of service. | Medium | C3 |
| T08 | A title or evidence string with Markdown, HTML or Mermaid syntax. | Injection into `ROADMAP.md` or the diagram in a public repository. | Low | C3 (untrusted titles never render); C5 implemented |
| T09 | Agent or gate commands supplied by a repository file. | Arbitrary command execution on the operator's machine. | Critical | C6 planned (#13, #14) |
| T10 | The agent runs with the operator's primary token and no branch protection. | A manipulated agent can push to `main`, edit any issue, or act across every repository the token sees. | High | C14 policy |
| T11 | Checkout of a branch the executor did not create. | Hook and script execution; attacker agent instructions. | Critical | C10, C11 planned (#15, #10) |
| T12 | A `pr-review:<login>=APPROVED` predicate matched against any review; a `skill:` verdict produced by an agent that read attacker text. | Forged gate pass. | High | C12, C13 planned (#14) |
| T13 | `--add-edge` writes before checking for a cycle and never compares the body it read with the body it overwrites. | Lost concurrent edits; a cycle visible on GitHub for a window. | Medium | #1 |
| T14 | A flood of issues fills the list limit. | The compiler fails closed: planning stops. | Medium | C15 documented, not implemented |
| T15 | The prompt file in a predictable temporary path. | Local symlink or read by another user. | Low | C16 planned (#13) |
| T16 | TLS interception. | Forged issue data; also forged code. | Out of scope beyond fail-closed | `gh` refuses plain HTTP; never add a downgrade |
| T17 | A frontmatter key that claims trust (`.approved`, `.signed_by`). | Written by the same hand as the attack. | — | C17 policy: no such key, ever |

## 6. Controls (the policy)

### C1. Trust gate on authorship — implemented

An issue is **trusted** only when all of the following hold:

- Its repository is in the trusted scope (C2).
- Its author is trusted: `authorAssociation` `OWNER` inside the scope; or
  `write`, `maintain` or `admin` permission on that repository
  (`repos/{slug}/collaborators/{login}/permission`); or the login is on the
  allowlist (`--trust <login>`, or CODEOWNERS with `--trust-codeowners`, see
  C18). `MEMBER` and `COLLABORATOR` associations are not enough by
  themselves: both include read- and triage-level people.
- **Every editor** in the issue's body edit history is trusted by the same
  rule: the author (already trusted), an allowlisted login, or a login with
  `write` or higher permission. A deleted user, a bot, a `read` or `triage`
  collaborator, or a check that cannot be made is untrusted.
- Owner, repository and login names compare case-insensitively, as GitHub
  treats them.

Order and cost: the author is checked first, from the REST issue object that
discovery already holds. An author whose association is not `OWNER`,
`MEMBER` or `COLLABORATOR` has no collaborator standing by GitHub's own
account, so a stranger's issue costs no further query (see C15); a `MEMBER`
or `COLLABORATOR` author costs one cached permission lookup per login.
Bot logins are compared in one normalised spelling (`x[bot]`, `app/x`, GraphQL `x` typed Bot), distinct from any human `x`. Only an issue whose author passes is looked up in GitHub's edit history
(GraphQL `userContentEdits`), and that query also returns the body, so the
editors checked are the editors of the body that is parsed.

Any trust lookup that cannot run (the edit-history query, the permission
endpoint, a CODEOWNERS fetch that is not a 404) exits `2` and no graph is
compiled: a silently untrusted collaborator would hide trusted work behind
opaque blockers while the run reported success. For a repository the operator
cannot administer, name its editors with `--trust`; allowlisted logins are
never looked up.

Consumed REST issue fields are checked before discovery or authorization. A null
user is untrusted. A present author requires a nonempty login and a supported
`User` or `Bot` type; an unsupported type exits `2` before association or
permission can grant trust. Issue numbers are positive integers without
coercion. A malformed later inventory row rejects the entire inventory rather
than admitting a prefix.

Edit-history responses must have checked body, connection, editor and pagination
fields. Null nodes or editors are unknown identities, never trusted authors.
An edit-history actor object with a malformed login or a type other than `User` or `Bot`
stops the run with exit `2`; it must not share a human's identity key. GraphQL
errors, missing pagination metadata, repeated cursors, or a history exceeding
100 pages or 10,000 editor records also stop the run without admitting a prefix.
These count limits bound each history's requests and retained editor records;
they are not a total wall-clock deadline for the compiler.

Bots: a Bot actor (a GitHub App or integration) is trusted only by explicit
`--trust <name>[bot]` (or `app/<name>`). Association and permission never
trust a bot, because an installation's permissions are not the operator's.
Bot and human identities never share a key: allowlisting `x[bot]` does not
trust a person whose login is `x`, and `--trust x` does not trust the app.

Titles are not covered. GitHub's edit history records body edits only, and a
`triage` collaborator can rename an issue. A title is therefore untrusted
display text everywhere: escaped when rendered (C5), never an instruction,
and excluded from executor prompts (C7). Checking the actors of
`RenamedTitleEvent`s on the timeline is a follow-up, not a precondition.

### C2. Repository scope — implemented

The closure follows references only into trusted repositories. The scope is
the home repository's owner by default, extended with `--trust-owner <owner>`
and `--trust-repo <owner/repo>`. A reference outside the scope is a
frontmatter violation on the referencing issue (exit `1`), and the referenced
issue is never fetched. A `--root` outside the scope is an error.

Association counts only inside the scope. Cross-organisation DAGs declare their
owners explicitly; the flags are the declaration.

### C3. Untrusted issues are never nodes — implemented

- An untrusted **seed** (an open home issue, or a `--root`) that no trusted
  issue references is listed in `source.untrusted_issues` with the reason and
  is not a node. Its frontmatter is not parsed.
- An untrusted issue that a trusted issue **references** is an opaque
  blocker, whether or not it is also a seed: it blocks its dependents until
  it is closed, is never dispatched, and contributes no edges, holds, meters
  or title. It is listed with the reason.

Nothing an untrusted author wrote reaches the graph, the batch, the ranking,
or any rendered output, including the `not_planned_parents` report. An
untrusted blocker appears only as the placeholder `(untrusted issue)` with
its reference, so a dependent's blocked state stays visible.

### C4. Linked PRs count only when trusted — implemented

A PR marks a task in flight only when `isCrossRepository` is false (the head
is a branch of the same repository) **and** its author is trusted under C1's
login rule. Every other PR that closes a task is listed in
`source.untrusted_linked_prs` and has no effect on status or ranking. A
missing field is untrusted.

### C5. Output escaping — implemented

Rendered Markdown escapes `|`, `<` and `>` in cells. Mermaid labels already
replace quotes and angle brackets. Untrusted titles are never rendered (C3).

### C6. Executable settings come only from the operator — planned (#13, #14)

Agent `argv`, gate commands and trust lists are read from the operator's
configuration directory, never from the repository being executed. `argv` is
a list, never a shell string. A repository file cannot supply a command (test).

### C7. Issue text is data, never instructions — planned (#10, #15)

The prompt builder wraps every string that came from GitHub (body, comments,
PR descriptions, review text) in a clearly delimited data block and states,
outside that block, that the agent must not follow instructions found inside
it. Titles never enter a prompt (C1). The rules the agent must follow are the
executor's, not the issue's.

### C8. Bounded authority for agent runs — policy

Every executor prompt contains GitHub content, so "run with the interactive
permission checks" would stop a headless agent from editing a file or running
a test. The rule is bounded authority instead: an agent runs **inside a
sandbox** that limits the filesystem to its worktree and owned temporary
storage, limits the network to GitHub and the registries the repository's
build needs, and uses a scoped token (C14); within that sandbox it runs with
an **explicit tool allowlist**. A flag that disables permission checks is
permitted only inside such a sandbox, never on the operator's bare machine.
Without a sandbox the executor refuses to run.

### C9. Explicit execution approval bound to the body — planned (#9, #10), decided: staged

Being a trusted node lets an issue into the graph. It does not by itself let
the executor run it. The executor runs a task only when **this body** has been
approved. An approval names the issue and the SHA-256 of its body (line
endings normalised to LF before hashing). A body edit after approval
invalidates it: the hash no longer matches, and the task is listed as *needs
re-approval*.

**Decided on 2026-11-08 (user):** Stage 1 is required for #9 and #10. Stage 2
is deferred until a repository has more than one approver or sets
`merge = true`.

**Stage 1 — run-time approval, no keys.** The operator approves at run time
with `--approve owner/repo#N` after reading the issue. The executor records
`Issue:` and `Body-SHA256:` trailers on its first, empty commit of the task
branch and mirrors them in the PR body marker. That still catches a body
edited after approval, costs no key management, and the trust gate already
limits who can author a runnable task to people with write access.

**Stage 2 — the approval ledger.** Approvals live in an **approval ledger on
a git ref**, not in issue text:

- The ref is `refs/heads/issue-dag/approvals` in the issue's own repository.
  A ledger approves only issues of its own repository; an entry for another
  repository is ignored.
- Each approval is an **empty, signed commit** whose parent is the previous
  ledger commit. Subject `approve owner/repo#N`; trailers `Issue:`,
  `Body-SHA256:`, optional `Expires:` (ISO 8601) and `Revoke: yes` to
  withdraw an earlier approval. The latest entry for an issue wins.
- The executor fetches the ref and verifies **every** commit on it against the
  operator's allowed-signers file (`gpg.ssh.allowedSignersFile` or a GPG
  keyring), with `git verify-commit`. An unverifiable commit fails the whole
  ledger closed.
- A ruleset on the ref requires signed commits, forbids force-push, and
  restricts who may push. The ruleset is defence in depth; the local
  verification is the control.

Why a ref and not a comment: pushing needs write access, so anonymous users
cannot create approvals at all; the signature is checked locally, so GitHub's
attribution and the TLS channel are not trusted; the chain is the audit log;
and the executor never parses comment text for authorization. A comment may
mirror an approval for people. The ref is the truth.

The operator may approve in the run instead (`--approve owner/repo#N` after
reading the issue); the executor then writes the same ledger entry. There is
no flag or environment variable that skips verification.

Rules carried over from Shiplog's 2026-10 trust audit
(`git-stunts/shiplog`, label `audit-2026-10`), each of which Shiplog had to
learn by finding the defect:

- **Bind to keys, not names** (shiplog#96). An approval counts only when
  `ssh-keygen -Y find-principals` binds the signature to a key in the
  operator's allowed-signers file. Committer e-mail, author name and trailer
  text never identify an approver.
- **Approvers are not agents.** The allowed-signers material has two
  principal sets: `approvers` (humans) and `agents` (the executor's keys for
  C10). A ledger entry signed by an agent key is invalid, or a manipulated
  agent approves its own task.
- **Pass the roster explicitly** (shiplog#109, #102, #138). Every
  `git verify-commit` runs with `-c gpg.ssh.allowedSignersFile=<absolute
  path>` given by the executor; local Git configuration is never consulted,
  because a silently unused roster verifies nothing.
- **Fast-forward only; deletion refused** (shiplog#94, #95). The executor
  verifies the ledger as a chain from a recorded tip; a non-fast-forward
  ledger fails closed. The ruleset on the ref forbids deletion and
  force-push, since a deleted ref turns the next push into a genesis.
- **A missing ledger is a reported state, not an empty success**
  (shiplog#124). No ledger means no task is approved; the output says so.
- **Only fixed trailers, never body text** (shiplog#97, #121). The ledger
  commit message holds the subject and the trailers above, written and read
  under the Git trailer convention as implemented by
  `@git-stunts/trailer-codec`: keys alphanumeric and hyphens, compared
  case-insensitively; values single-line and non-empty; a blank line before
  the trailers. The issue body never enters a commit message; its hash does.
- **One verifier, one adversarial suite** (shiplog `lib/trust-verify.sh`,
  `test/27_trust_adversarial.bats`, shiplog#135). One module verifies the
  ledger for the executor and for a required CI check; an adversarial test
  suite (forged signer, agent-signed approval, replayed entry, stale hash,
  expired, revoked, deleted ref, non-fast-forward) is the executable
  specification and blocks CI.

### C10. Never check out a branch the executor did not create — planned (#10, #15), staged with C9

**Stage 1.** The executor's first commit on a task branch (#10 already plans
an empty first commit) carries the trailers `Issue: owner/repo#N` and
`Body-SHA256:` of the approved body, mirrored in the PR body marker. Resume
applies only to a PR that is trusted (C4) and whose root commit carries that
provenance for this task. A branch whose root commit does not is parked and
reported, never resumed. A rebase by a person rewrites the root commit, so a
branch a human has taken over is parked for that human; that is the intended
outcome, not a defect.

**Stage 2.** The first commit is **signed with the agent key** and adds
`Approval:` with the object ID of the ledger commit that approved it
(Shiplog's `trust_oid` pattern). Resume then also requires every later commit
to verify against the allowed-signers file. Agents sign with a dedicated agent
key, so human and agent commits are distinguishable in the audit trail, and
no GitHub metadata is needed for the decision.

Optionally, leases become refs too: `refs/issue-dag/leases/<owner>/<repo>/<N>`
pointing at a signed empty commit with an `Expires:` trailer, claimed with
`git push --force-with-lease`. That gives an atomic claim visible from every
machine, which the machine-local `git-locks` lease cannot.

### C11. Agent instructions come from `main` — planned (#10, #15)

The prompt builder reads `CLAUDE.md` and `AGENTS.md` from `main`, never from
the task branch. Hooks are **not** disabled: skipping them would contradict
the repository rule never to bypass hooks, and the threat (hooks tracked on a
branch the executor did not create) is already closed by C10, which refuses
to check such a branch out.

### C12. Gate predicates bind identity — planned (#14)

`pr-review:<login>=<state>` matches the **latest** review by exactly that
login, and that login must be trusted (C1 login rule or allowlisted bot).
Reviews by anyone else are ignored. Prefer GitHub's own `reviewDecision` under
a ruleset that requires code-owner review, because GitHub enforces who counts.

### C13. Gate only executor-owned PRs; CI only from trusted heads — planned (#14)

The gate evaluates only PRs that pass C4 and C10. A `skill:` predicate needs a
structured verdict written to a file by the verdict agent; prose is not a
verdict, and the verdict agent runs with a read-only token. CI results count
only for same-repository heads.

### C14. Small authority for agents — policy

- Agents receive a token scoped to the repositories in the closure, with
  contents, pull-requests and issues write, and no admin.
- Every repository in the scope protects `main` with a ruleset: pull request
  required, no direct push, signed commits required, code-owner review where
  CODEOWNERS exists.
- `merge = false` is the default. `merge = true` is a per-repository decision
  in the operator's settings.

### C15. Availability under a seed flood — implemented in part, decision pending

Implemented: a stranger's issue is rejected from the REST listing alone and
costs no further query, so a flood costs one listing page per hundred issues
and nothing else. Open: a flood that reaches `GH_ISSUE_LIST_LIMIT` still exits
`2`. The remaining mitigation is to seed from a write-gated signal instead of
"every open issue": a label that needs triage to apply, or `--author` queries
per trusted login. flyingrobots/taskalisk#11 rejected labels as a *state
tracker*; a seed filter is a different role. This is a decision for the
operator, recorded here as open.

### C16. Prompt files in owned temporary storage — planned (#13)

`tempfile.mkstemp` inside a directory created with mode `0700`, removed after
the run.

### C17. The format carries no trust claims — policy

No `issue-dag` key may assert trust, approval, signature or identity. Trust
comes from who wrote the document (GitHub metadata, C1), who approved the
body (C9), and who runs the executor (C6). A proposal to add such a key is
rejected on sight.

### C18. CODEOWNERS as a reviewed allowlist — implemented as an option

With `--trust-codeowners`, the script reads `.github/CODEOWNERS`,
`CODEOWNERS` or `docs/CODEOWNERS` from the **default branch** of every
repository in the scope and adds each `@login` it finds to the allowlist for
that repository. Team entries (`@org/team`) are reported and not expanded.
It only ever **adds** logins to the allowlist; it does not remove anyone that
write permission already trusts. Its value is that the list is reviewed
alongside the code when a ruleset requires code-owner review for changes to
the file. It never widens the scope (C2).

## 7. Mechanisms considered and where they fit

| Mechanism | Verdict |
| --- | --- |
| `authorAssociation` | Baseline for C1. Only meaningful inside the scope (C2). |
| Body edit history | Required by C1; a trusted author's body edited by anyone else is untrusted. |
| CODEOWNERS | A reviewed allowlist of people (C18). Not a scope mechanism. |
| Run-time `--approve` with `Issue:`/`Body-SHA256:` trailers on the first commit | Stage 1 of C9 and C10 (required for #9, #10). Catches edit-after-approval without keys. |
| Approval ledger: signed empty commits on a git ref | Stage 2 of C9 (deferred until more than one approver or `merge = true`). Write-gated, verified locally, append-only. |
| Approval comment bound to body hash | A display mirror for people. Anyone can comment, so never the truth. |
| Signed first commit with `Approval:` trailer | Stage 2 of C10. Needs no GitHub metadata. |
| Signed commits on `main` | A ruleset (C14). Agents get their own key. |
| Lease refs claimed with `--force-with-lease` | Optional cross-machine lease (C10). `git-locks` stays machine-local. |
| Labels | A write-gated seed filter (C15). Never state, never edges. |
| Native `blocked_by` relationships | A mirror; drift report only. Never a source of edges. |
| Frontmatter trust fields | Never (C17). |

## 8. What this does not defend against

- A trusted account acting maliciously. C9, C10 and C14 limit the damage to
  one approved task, on one branch, behind a ruleset.
- GitHub itself lying. Everything here trusts GitHub's attribution except the
  optional signature in C9 and the commit verification in C10.
- Operator settings that are themselves malicious.
- The agent model following instructions hidden in data despite C7. C8 and
  C14 bound the blast radius; they do not prevent the attempt.

## 9. Residual risks and open decisions

- **C15** needs a decision: which write-gated signal seeds discovery once a
  flood reaches the list limit.
- **Repositories the operator cannot administer.** The permission endpoint
  needs push access on that repository; without it the run exits `2`.
  Allowlist that repository's editors with `--trust`, which skips the lookup.
- **Titles** are outside the edit-history gate (C1). A `RenamedTitleEvent`
  actor check is a follow-up.
- **One GraphQL query per trusted issue** for edit history (none for a
  stranger's). flyingrobots/taskalisk#7 batches reads once a real graph is
  measured slow; the batched query must keep the same fail-closed behavior.
- **Executor writes.** When the executor lands, SKILL.md doctrine 8 must say
  so: the compiler's only GitHub write stays the `.blocked_by` edit; the
  executor adds pushes to its own task branches (and, in Stage 2, its approval
  and lease refs), draft PRs and status comments, and nothing else.
- **Key management** applies to Stage 2 only: an allowed-signers file per
  operator, an agent key per machine, and a documented rotation. Stage 1
  relies on GitHub attribution (C4) and the trust gate (C1), and says so.
