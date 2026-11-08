# Taskalisk

Taskalisk, an agent skill: compile GitHub issues into a transitively reduced
precedence DAG from their frontmatter (`docs/frontmatter-model.md`), across
repositories, rank the open frontier, and edit edges in frontmatter. The skill itself is in
`skills/taskalisk/`; agent skill folders link to it.

Repositories are public, so anyone can file an issue or a fork PR. The threat
model and the binding security policy are in `docs/threat-model.md`; the
compiler applies its trust gate on every run.

## Test

```sh
python3 -m unittest discover -s tests
```

The tests run offline. `tests/fake_gh.py` stands in for `gh` and logs every
call, so a test can check which repository each request went to.
