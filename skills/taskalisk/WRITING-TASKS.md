# Writing a task

Read this before you propose a new task or a split.

A task is one **outcome**: one observable change that one pull request
delivers and that leaves `main` working.

## The one-outcome test

Put every task through all three checks before it enters a proposal.

1. **One sentence.** State the outcome as one sentence with one subject and
   one verb. An outcome that needs "and", a semicolon or a second sentence is
   two tasks.
2. **One review.** A reviewer approves or rejects the whole pull request. If
   half of it could merge alone and be useful, that half is its own task.
3. **One need.** Look at each task that will depend on this one. If a
   dependent needs only part of it, split along that line, and give the
   dependent an edge to the part it needs.

A task that fails any check is split, and each piece takes the test again.

## Signs of a bundle

Each of these means the test will probably fail:

- The title joins two things: "A and B", "A; B".
- The outcome names two commands, two behaviours or two artifacts.
- The acceptance checks test behaviours that could pass or fail apart.
- A measurement or a decision rides along with code. Give it its own task,
  with `.type: research` or `.type: decision`.
- The scope list reads as a sequence of steps, each with its own result.

## Body sections

Write each task body from the canonical template for its `.type`, in
[`templates/issue/`](templates/issue/). Every template opens with these
sections after the frontmatter, under these exact headings and in this order,
and its type's own sections follow them:

| Section | Holds |
| --- | --- |
| Outcome | The one sentence from check 1 |
| Scope | What the pull request contains |
| Out of scope | What a reader might expect that it leaves out, and where that work lives |
| Prerequisites | Each `.blocked_by` entry with the reason it must close first |
| Safe intermediate state | What `main` is like after this merges and before its dependents do |
| Acceptance | Exact, observable results, as a checklist |

## Size

`.size_hours` above 8 draws a warning: the task is probably not atomic. A
task that passes the test is usually a few hours. Estimate after splitting; a split
often shows work the bundled task hid, so the total may rise.

## Report the plan at its true size

A plan of ten bundled tasks reads as small work. The same plan as two dozen
single-outcome tasks is the truth. When you present a plan, state:

- the number of tasks and the total of their estimates;
- the critical path and its hours;
- every piece of known work the plan leaves out, by name.

## Done

The proposal is ready when every task in it has passed all three checks, and
the proposal states the task count, the total hours, the critical path with
its hours, and the work left out.
