# Planning profile `issue-dag-planning/2`

Status: accepted. This document is the normative definition of the profile.

A planning profile holds the rules that apply to a set of documents and the
observed state of their issues: discovery, the cross-document rules, edge
satisfaction, task status, readiness, ranking, resource conflict and batch
selection, and the outcome of a run. This profile states the rules that the
reference implementation, the Python Taskalisk compiler at
`flyingrobots/taskalisk@8e4cb73`, applies to [`issue-dag/2`](../formats/issue-dag-2.md)
documents. Where this profile and that implementation differ, the difference
is listed in [the reconciliation notes](../notes/python-differences.md) and
is classified by the corpus work, not silently resolved.

Only statements with a label such as **G4** are normative. Everything else,
including examples and blocks marked *Commentary*, is informative. The key
words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119 and RFC 8174 when
they appear in capitals.

## 1. Inputs

A run of a planner takes run parameters and observations, and produces a
plan.

**I1. Run parameters.**

- A *home repository* `H`: the repository the planner works for.
- Optionally, a non-empty list of *root references*.
- A *read scope*: the set of repositories the run may read. It includes `H`.
  A planner obtains it from its trust policy.
- A map from semaphore names to capacities, each a positive integer. It may be
  empty.

**I2. Root references.** Each root reference MUST be a reference under the
format's rule L1, in a repository of the read scope. Otherwise the run is
rejected.

**I3. Observations of an issue.** For each reference the run reads, the
planner observes:

- whether the reference resolves to an issue or to a pull request;
- the address the issue has now, which differs from the reference when the
  issue was transferred;
- its state, `open` or `closed`, and for a closed issue its close reason,
  which is `completed`, `not_planned` or another value;
- its *admission decision*, `admitted` or `not admitted`, made by the
  planner's trust policy;
- for an admitted issue, its body: the body that the admission
  decision covered.

**I4. Observations of the home repository.** When the run has no root
references, the planner observes the complete list of `H`'s open issues. In
every run it observes the complete list of `H`'s open pull requests, and for
each pull request the issues it closes, whether it is a draft, and its
admission decision.

**I5. Completeness.** An observation is required when a rule of this profile
reads it. A required observation that the planner cannot make, or cannot show
to be complete, is *unavailable*. A listing that may have been truncated is
unavailable. A draft flag that is not a boolean is unavailable.

> *Commentary.* The trust policy is outside the format and outside this
> profile. The profile fixes what an admission decision causes, not how it is
> made. Taskalisk's trust policy is the threat model in
> `flyingrobots/taskalisk`, `docs/threat-model.md`: an issue is admitted when
> its repository is in scope and its author and every editor of its body are
> trusted; a pull request is admitted when its head branch is in the same
> repository and its author is trusted.

## 2. Outcome

**F1. Outcome classes.** A run ends in exactly one of four classes, checked
in this order:

1. *rejected*: a run parameter is invalid (I2);
2. *incomplete*: a required observation is unavailable;
3. *invalid*: the observations are complete and some document, cross-document
   rule, discovery rule (D3 to D5) or graph rule fails;
4. *planned*: none of the above.

**F2. No partial plan.** An incomplete run MUST NOT produce a graph, a ready
set or a batch. A planner MUST NOT treat an unavailable observation as an
empty one.

**F3. Invalid runs.** An invalid run MAY report the graph it computed, for
diagnosis. Its ready set and batch MUST NOT be used to start work.

**F4. What an invalid run reports.** An invalid run reports each violation
with the issue it is attached to. The set of issues with violations is
observable. The wording of a message is not.

> *Commentary.* The reference implementation exits with status 1 for an
> invalid run, 2 for an incomplete one, and 0 for a plan. It reports a bad
> `--root` with status 2, as an input failure.

## 3. Discovery

**D1. Seeds.** With root references, the seeds are the root references.
Without them, the seeds are the open issues of `H` that are not pull
requests.

**D2. Closure.** The planner visits the seeds and then every reference that
rule D8 adds, until no reference is left. A reference is visited once.
References are compared under the format's rule L1. The order of visits does
not change the result.

**D3. Out of scope.** A reference to a repository outside the read scope is
never read. Each document that names it receives a violation. It is not a
node.

**D4. Pull request.** A reference that resolves to a pull request receives a
violation and is not a node.

**D5. Transferred.** A reference whose issue now has a different address
gives a violation to each document that names it. When it is a root
reference that no document read in the run names, the violation is the
reference's own. It is not a node.

**D6. Not admitted.** An issue whose admission decision is `not admitted` is
an *opaque node* and its body is not read as a document. It is marked
*untrusted*. If it is a seed and no document read in the run names it, it is
not a node and is only listed.

**D7. No frontmatter.** An admitted issue whose body has no frontmatter block
(format rule C3) is an *opaque node*, with one exception: a seed of a run
without root references that no document read in the run names is
*unmodeled*. It is listed and is not a node.

**D8. Documents.** An admitted issue whose body has a frontmatter block is a
document. It is validated under its declared version and under X1, whether
the issue is open or closed. The planner then adds to the closure every item
of `.blocked_by`, when `.kind` is `task`, and of `.children`, when `.kind` is
`container`, that is a reference and is not the issue's own address. It does
so even when the document has violations.

**D9. Containers.** A document whose `.kind` is `container`, valid or not, is
a container and not a node. It is listed with its children. Discovery walks
its children whatever its state.

> *Commentary.* Discovery follows only what a document says about itself, so
> it reaches the prerequisites and the container members of the seeds and
> nothing downstream of them. A plan's discovery scope is its seeds, the
> repositories it read, and the references it could not follow.

## 4. Cross-document rules

**X1. Own address.** The `.id` of a document MUST equal the address of the
issue that holds it. Otherwise the document receives a violation: it was
copied or transferred.

**X2. No container prerequisite.** An item of the `.blocked_by` of an open
task MUST NOT name an issue whose document is a container. Such an item gives
the task a violation and makes no edge.

**X3. Unknown prerequisite.** An item of the `.blocked_by` of an open task
that names an issue which is neither a node nor a container is unknown, and
the run is invalid.

## 5. The graph

**G1. Nodes.** The nodes are the opaque nodes and the issues that hold a
document that is not a container, valid or not.

**G2. Completion.** A node whose issue is closed is *complete*, whatever its
close reason. All other nodes are *open*.

**G3. Edges.** For each open task `b` and each distinct reference `a` in its
`.blocked_by`, other than the issue's own address (as D8 excludes it) and
those covered by X2 and X3:

- if `a` is complete, the edge is *satisfied*: `a` is listed as a completed
  prerequisite of `b`, and when `a` was closed as `not_planned` the pair is
  also listed for review;
- if `a` is open, the graph has the edge `(a, b)`: *`a` must be complete
  before `b` is correct*.

A complete node has no edges, and its own `.blocked_by` is not evaluated for
edges.

**G4. Cycles.** If the edges form a cycle, the run is invalid. The reported
cyclic nodes are the open nodes that remain after repeatedly removing every
open node with no incoming edge: the members of every cycle and every node
downstream of one.

**G5. Reduction.** The *reduced* graph has the edge `(u, v)` exactly when
`(u, v)` is an edge and no other path leads from `u` to `v`. The removed edges
are listed as redundant.

> *Commentary.* For an acyclic graph the reduction is unique (Aho, Garey and
> Ullman, 1972). The reduced graph has the same reachability as the graph, so
> rules K1, K2 and Q1 give the same results on either.

## 6. Status

**S1. Linked pull requests.** The linked pull requests of a node are the
admitted open pull requests of `H` that close it. A node outside `H`, and an
untrusted node, has none.

**S2. Status.** The status of an open node is the first that applies:

1. `in-review`, if a linked pull request is not a draft;
2. `wip`, if it has linked pull requests, all drafts;
3. `blocked`, if it is opaque;
4. `in-progress` if `.status` is `active`, `parked` if it is `parked`,
   `blocked` if it is `blocked`;
5. `open`.

> *Commentary.* A linked pull request overrides every `.status`, including
> `blocked`. A task marked `blocked` with a linked pull request can therefore
> be batched. The `/3` profile changes this (`flyingrobots/taskalisk#35`).

## 7. Readiness

**Q1. Ready set.** The ready set is the set of open nodes with no incoming
edge: every prerequisite is complete. It is also called the open frontier.

**Q2. Dispatchable.** A ready node is dispatchable unless its status is
`blocked` or it is opaque. Only dispatchable nodes enter a batch.

## 8. Ranking

For an open node `u`:

**K1.** `Descendants(u)` is the set of open nodes reachable from `u` along
edges, not including `u`.

**K2.** `Depth(u)` is the number of nodes on a longest path that starts at
`u`, counting `u`. A node with no outgoing edge has depth 1.

**K3.** `Out(u)` is the number of edges that leave `u` in the reduced graph.

**K4.** `InFlight(u)` is 1 when the status of `u` is `in-progress`, `wip` or
`in-review`, and 0 otherwise. `Parked(u)` is 1 when the status of `u` is
`parked`, and 0 otherwise.

**K5. Score.**

```text
Score(u) = 1000·InFlight(u) + 500·Parked(u)
         + 100·|Descendants(u)| + 10·Depth(u) + Out(u)
```

**K6. Order.** Nodes are ranked by descending score. Equal scores are ordered
by the node's identifier, the canonical form of its reference, compared as a
sequence of Unicode code points, ascending.

**K7. Waves.** The level of `u` is the number of edges on a longest path that
ends at `u`. Wave `k` holds the nodes of level `k`, each wave in rank order.
Wave 0 is the ready set.

**K8. Critical path.** A critical path exists only when the edges have no cycle
(G4), as in every planned run, and some node is open; a run whose edges form a
cycle, or that has no open node, reports none.
The critical path starts at the open node with the greatest pair (level,
identifier) and steps, while the current node has a predecessor in the
reduced graph, to the predecessor with the greatest pair (level, identifier).
The path is reported from its first node to its last.

> *Commentary.* K6 compares identifiers as text, so `o/r#10` ranks before
> `o/r#9` when their scores are equal. K7 and K8 are reported but are not part
> of readiness, ranking or batch selection.

## 9. Resources and batch

**B1. Key conflict.** For a resource key `k`, let `T(k)` be `k` when `k` ends
with `/`, and `k` followed by `/` otherwise. Two keys `k` and `k'` conflict
when `k = k'`, or `T(k)` is a prefix of `T(k')`, or `T(k')` is a prefix of
`T(k)`.

**B2. One key space.** Keys are compared across all repositories. A key
declared by a task in one repository conflicts with an equal key declared in
another.

**B3. Capacity.** The capacity of a semaphore is its run parameter. A
semaphore without a parameter has capacity 1. Each such name that appears in
a claim of a dispatchable ready node that B5 considers is reported.

**B4. Need.** The need of a node for a semaphore is the sum of the slots of
its claims with that name.

**B5. Selection.** The batch starts empty. The planner considers each
dispatchable node of the ready set in rank order:

1. if any of its keys conflicts with a key of a node already in the batch, it
   is skipped, with the reason `holds conflict`;
2. otherwise, if for some semaphore the needs of the nodes already in the
   batch plus its own need exceed the capacity, it is skipped, with the
   reason `semaphore full` and the names of those semaphores;
3. otherwise it joins the batch.

> *Commentary.* B1 treats every key as a subtree, so `docs` conflicts with
> `docs/plans` as well as `docs/` does. The `/3` profile scopes keys to their
> repository (`flyingrobots/taskalisk#37`). B5 is greedy: a high-ranked node
> that joins the batch can exclude several lower-ranked ones.

## 10. Admission consequences

**T1.** A planner MUST NOT publish, in any output, text that the author or an
editor of an untrusted issue or pull request wrote, including its title. It
MAY publish the reference, the URL, the state, the author's login and the
reasons for the decision.

**T2.** An untrusted node contributes no edges, holds no resources and is
never dispatchable.

## 11. Reported lists

**W1.** A plan MUST report, besides the outcome, the graph, the ready set, the
ranking and the batch, at least:

- the containers, with their children;
- the unmodeled issues (D7) and the opaque nodes;
- the untrusted issues and the untrusted pull requests that close an issue;
- for each open node, its completed prerequisites (G3);
- the satisfied edges whose prerequisite was closed as `not_planned` (G3);
- the redundant edges (G5);
- the warnings of the documents read (format rule V10).

## 12. Observables

The compatibility observables of [the version policy](../versions.md#compatibility-claims)
correspond to this profile as follows:

| Observable | In this profile |
| --- | --- |
| O3, structure | Each document's declared `.blocked_by`, `.children`, `.holds` and `.meters`, as decoded. The edges a run derives from them (G3) depend on issue state and are not part of O3 |
| O4, readiness | The ready set (Q1) and the dispatchable subset (Q2) |
| O5, ranking | The order of the ready set (K6) |
| O6, batch | The batch and the skipped nodes with their reasons (B5) |

## 13. Not in this profile

- Lifecycle findings. This profile evaluates none of the four lifecycle rules
  of Taskalisk's decision 0001 (not the format's value rules L1 to L4); their
  consequences are defined by a later profile (`flyingrobots/taskalisk#33`).
- Completion by `.type`. Under this profile a closed issue is complete for
  every type (G2).
- The evaluation record, which names the formats and the profile a plan used
  (`flyingrobots/taskalisk#30`).
- Writes. An edge edit is specified in [the edge-edit contract](../contracts/edge-edit.md).
- Graph metrics, such as edge density and the count of isolated nodes, and
  hints such as local branch names that contain an issue's number. A planner
  may report them; no rule depends on them.
