# issue-dag

The `issue-dag` agent skill: compile GitHub issues and their native
`blocked_by` dependencies into a transitively reduced precedence DAG, rank the
open frontier, and record edges on GitHub. The skill itself is in
`skills/issue-dag/`; agent skill folders link to it.

## Test

```sh
python3 -m unittest discover -s tests
```

The tests run offline. `tests/fake_gh.py` stands in for `gh` and logs every
call, so a test can check which repository each request went to.
