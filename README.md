# Taskalisk

Taskalisk, an agent skill: compile GitHub issues into a transitively reduced
precedence DAG from their frontmatter (`docs/frontmatter-model.md`), across
repositories, rank the open frontier, and edit edges in frontmatter. The skill itself is in
`skills/taskalisk/`. Install it from a release (below), not by linking a working
checkout.

Repositories are public, so anyone can file an issue or a fork PR. The threat
model and the binding security policy are in `docs/threat-model.md`; the
compiler applies its trust gate on every run.

## Install a release

Each release has `taskalisk-v<version>.zip` and `SHA256SUMS`. The ZIP holds one
`taskalisk/` folder: the skill, its compiler, the bundled frontmatter and
threat models in `references/`, and a per-file `SHA256SUMS`.

```sh
gh release download v1.0.0 --repo flyingrobots/taskalisk --pattern 'taskalisk-v1.0.0.zip' --pattern SHA256SUMS
shasum -a 256 -c SHA256SUMS
unzip taskalisk-v1.0.0.zip -d ~/.agents/skills
(cd ~/.agents/skills/taskalisk && shasum -a 256 -c SHA256SUMS)
```

Use your agent host's skills folder in place of `~/.agents/skills`. Move an
existing `taskalisk/` folder aside before installing a newer release.

## Build a release

```sh
python3 scripts/build_skill_release.py --version 1.0.0 --out .runs/release-v1.0.0
```

The builder replaces the links in `skills/taskalisk/references/` with the
documents they name in `docs/`, refuses a link that leaves the repository,
and never overwrites an output directory. Identical sources give identical
archive bytes.

## Test

```sh
python3 -m unittest discover -s tests
```

The tests run offline. `tests/fake_gh.py` stands in for `gh` and logs every
call, so a test can check which repository each request went to.
