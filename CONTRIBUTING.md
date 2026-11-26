# Contributing

Thank you for helping. Taskalisk plans its own work, so contributions follow the same rules its
agents do. [AGENTS.md](AGENTS.md) is the full version; this is the short one.

## Before you start

- Every open issue carries `issue-dag/2` frontmatter. File a new issue from one of the templates in
  `.github/ISSUE_TEMPLATE/`, and set its `.id` to the number GitHub assigns.
- Pick work from the compiled frontier:
  `python3 skills/taskalisk/scripts/taskalisk.py --from-github --human`.
- New features go to the Rust rebuild, not the Python compiler
  ([decision 0001](docs/decisions/0001-rust-issue-dag-contract.md)); defect fixes may land in Python.

## How a change lands

- Work on a branch and open a draft pull request that says `Closes flyingrobots/taskalisk#N`.
- Write the tests first and show them failing for the intended reason; then make them pass. Every
  change to `skills/taskalisk/scripts/taskalisk.py` comes with a test, and a security control
  without a test is not implemented.
- Never amend, rebase or force-push a pushed branch, and never skip hooks.
- `python3 -m unittest discover -s tests` runs the offline suite; CI runs it on Python 3.9 and 3.13.

## The merge gate

A pull request merges only with a Baker Street `READY`, no unresolved review threads or open review
requests, and green CI. The merge records all three.

## License

By contributing you agree that your contribution is licensed under the
[Apache License 2.0](LICENSE).
