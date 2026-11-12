# Taskalisk

Taskalisk, an agent skill: compile GitHub issues into a transitively reduced
precedence DAG from their frontmatter (`docs/frontmatter-model.md`), across
repositories, rank the open frontier, and edit edges in frontmatter. The skill itself is in
`skills/taskalisk/`; agent skill folders link to it.

Repositories are public, so anyone can file an issue or a fork PR. The threat
model and the binding security policy are in `docs/threat-model.md`; the
compiler applies its trust gate on every run.

## Test

Prepare the pinned verification tools with uv 0.12.19. Dependency installation
uses the network; the tests themselves run offline.

```sh
uv sync --locked --no-editable --group dev
uv run --no-sync python -W error -m unittest discover -s tests
```

`tests/fake_gh.py` stands in for `gh` and logs every
call, so a test can check which repository each request went to.

The verification range is CPython 3.9–3.13 on macOS and Linux; CI pins each
interpreter patch and local development uses 3.13.15. The CLI has no runtime
package dependencies. [The verification decision](docs/decisions/0001-python-verification.md)
describes the ongoing gate adoption and command resource limits.

For changes to the compiler, follow the [contributor verification guide](CONTRIBUTING.md).
