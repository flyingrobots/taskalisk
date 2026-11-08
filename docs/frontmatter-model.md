# Frontmatter model (`issue-dag/2`)

**Status**: Accepted on 2026-11-08. Version 2 replaced version 1 on the same day.

Taskalisk reads this format. The format name (`issue-dag`) describes the data and
is independent of the tool's name, so a tool rename never rewrites an issue.

The frontmatter of each issue is the only input to the DAG. The skill does not
read labels, milestones, body sections, or GitHub issue relationships.

## Carrier

The frontmatter is the first fenced code block of the issue body, with the info
string `yaml`. Only blank lines can come before it.

````markdown
```yaml
.dag: issue-dag/2
.id: flyingrobots/geordi#81
.kind: task
.type: feature
.blocked_by: [flyingrobots/geordi#78, flyingrobots/bunny#199]
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

Every reference is `owner/repo#123`, where `owner/repo` is the path after
`github.com`. A bare `#123` or `123` is invalid everywhere: in `.id`,
`.blocked_by`, `.children`, and the command line. Output node ids use the same
form.

Why: GitHub can transfer an issue to another repository, and a transfer does
not rewrite the frontmatter of other issues. A repository-relative reference
would then point at an unrelated issue without any error. A qualified
reference fails loudly instead. GitHub answers the old address with the moved
issue, and the skill reports `reference X moved to Y (transferred)`. A
transferred issue's own `.id` also stops matching, so its block fails too.

## Fields

| Key | Required | Value |
| --- | --- | --- |
| `.dag` | always | `issue-dag/2` |
| `.id` | always | The issue's own `owner/repo#N`. It must match the issue, so a copied or transferred block fails. |
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

## Versions

`.dag` versions the whole set of `.` fields. Because an unknown `.` key fails
the run, any new field is a new version. A retired version fails with a
message that names the migration.

| Version | Status | Change |
| --- | --- | --- |
| `issue-dag/1` | Retired | Allowed repository-relative `#N` references. |
| `issue-dag/2` | Current | Every reference is `owner/repo#N`. |

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
