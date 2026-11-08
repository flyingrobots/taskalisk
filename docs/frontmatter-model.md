# Frontmatter model (`issue-dag/1`)

**Status**: Accepted on 2026-11-08.

The frontmatter of each issue is the only input to the DAG. The skill does not
read labels, milestones, body sections, or GitHub issue relationships.

## Carrier

The frontmatter is the first fenced code block of the issue body, with the info
string `yaml`. Only blank lines can come before it.

````markdown
```yaml
.dag: issue-dag/1
.id: flyingrobots/geordi#81
.kind: task
.type: feature
.blocked_by: [#78, flyingrobots/bunny#199]
.size_hours: 2
area: rust-toolchain.toml
```
````

A fenced block renders well on GitHub. A YAML block between `---` lines does not.

## Prefix

Keys that the skill owns start with `.`. All other keys are free-form notes for
people and agents, and the skill ignores them. The skill rejects an unknown key
that starts with `.`, so a typo cannot silently drop an edge.

The `.` prefix is legal in YAML keys, JSON keys, GitHub label names, and shell
words without quotes. The alternatives fail somewhere:

| Prefix | Problem |
| --- | --- |
| `!` | YAML tag indicator (the key must be quoted). Shell history expansion. CodeRabbit uses `!` for label exclusion. |
| `@`, `` ` `` | Reserved indicators in YAML. |
| `%` | YAML directive indicator at the start of a line. |
| `~` | Shell tilde expansion (`~name` is a home directory). |
| `$` | Shell parameter expansion inside double quotes. |
| `/` | Looks like a path. Lock keys already contain `/`. |

## References

`#123` (or `123`) names an issue in the repository that holds the frontmatter.
`owner/repo#123` names an issue in any repository. The skill reports node ids
relative to the home repository (the one that `--repo` resolves to).

## Fields

| Key | Required | Value |
| --- | --- | --- |
| `.dag` | always | `issue-dag/1` |
| `.id` | always | The issue's own reference. It must match the issue, so a copied block fails. |
| `.kind` | always | `task` (an executable node) or `container` (it groups other issues and never blocks) |
| `.type` | task | `feature`, `bug`, `decision`, `research`, `investigation`, `spike`, or `task` |
| `.blocked_by` | task | List of references that must be closed before this task is correct. `[]` is allowed. The only edge field. |
| `.children` | container | Ordered list of member references, across repositories. Discovery walks it. |
| `.size_hours` | no | Integer estimate. Above 8 is a warning: the card is probably not atomic. |
| `.holds` | no | `git-locks` keys held exclusively for the whole task. |
| `.meters` | no | Semaphore slots held for the whole task: `name` (1 slot) or `name*N`. |
| `.status` | no | `active`, `parked`, or `blocked`. Open or closed comes from GitHub, never from the frontmatter. |

A task must not have `.children`. A container must not have `.blocked_by`. A
`.blocked_by` entry must not name a container.

## Completion

A closed issue is complete, whatever its frontmatter says. A blocker closed as
`not_planned` is listed for review, because it still satisfies the edge.

## Discovery

The seeds are the open issues of the home repository, or the `--root`
references when given. The skill follows `.blocked_by` and `.children` into any
repository until the closure is complete.

An issue without frontmatter is *unmodeled*. A home seed without frontmatter is
listed and is not a node. A referenced issue without frontmatter becomes an
opaque node. It blocks its dependents until it is closed, and it is never
dispatched.

## Resources

Resources only matter for work that shares something for its whole duration:
the same worktree, the same container, a device, or a system-wide resource with
exclusive access. Separate worktrees need no repository path locks. Short
commands, such as a heavy build, still acquire their `git-locks` keys when they
run. Those run-time locks do not belong in `.holds`.

- `.holds`: two tasks conflict when a key of one is equal to, or a subtree
  prefix of, a key of the other.
- `.meters`: a batch uses at most the capacity of each semaphore. The capacity
  comes from `--sem-capacity name=N`. An unknown capacity counts as 1
  (exclusive), and the output says so.

There is no default resource.

## GitHub relationships

GitHub sub-issues and `blocked_by` relationships are optional mirrors for the
GitHub interface. `--compare-relationships` reports drift between them and the
frontmatter. The frontmatter wins.

## Failure

The run fails closed. A `gh` failure exits `2`. An invalid frontmatter in the
closure, an unknown reference, or a cycle exits `1`.
