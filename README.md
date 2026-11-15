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
python3 scripts/build_skill_release.py --version 1.0.0 --ref v1.0.0 --out .runs/release-v1.0.0
```

The builder packages the files tracked under `skills/taskalisk/` at the
committed revision `--ref` (default `HEAD`), read from Git rather than the
working folder. Untracked, ignored and uncommitted files never enter a
release, and a checkout without symlink support builds the same archive.
Each link in `skills/taskalisk/references/` is replaced by the tracked
document it names in `docs/`. A link that leaves the repository, names an
untracked file or names another link is refused. An existing output
directory is never overwritten, and a failed build leaves none behind. The
same revision always gives identical archive bytes.

`skills/taskalisk/references/` holds symlinks. A checkout made without
symlink support, such as Git for Windows by default, shows them as one-line
files naming their targets; read `docs/` directly there. Release archives
always contain the documents themselves.

## Test

```sh
python3 -m unittest discover -s tests
```

The tests run offline. `tests/fake_gh.py` stands in for `gh` and logs every
call, so a test can check which repository each request went to.
