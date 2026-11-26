# Taskalisk

<img width="50%" height="50%" alt="taskalisk-card" src="https://github.com/user-attachments/assets/cce059c6-0ae4-417e-b44b-a171e598f498" />

Taskalisk, an agent skill: compile GitHub issues into a transitively reduced
precedence DAG from their frontmatter (`docs/frontmatter-model.md`), across
repositories, rank the open frontier, and edit edges in frontmatter. The skill itself is in
`skills/taskalisk/`. Install it from a release (below), not by linking a working
checkout.

A second skill, `skills/taskalisk-execute/`, is the procedure for executing a compiled
frontier: coordinator-assigned dispatch, draft pull request first, a fresh-context
Baker Street review, and a strict merge gate. It is a written specification, not an
executor, and it is not part of the release ZIP yet.

Repositories are public, so anyone can file an issue or a fork PR. The threat
model and the binding security policy are in `docs/threat-model.md`; the
compiler applies its trust gate on every run.

## Output

Every line the compiler prints, on stdout and stderr, is JSON under a declared,
separately versioned schema, written through the vendored
[Parley](https://github.com/flyingrobots/parley) writer: the plan summary
first, then the ranked frontier, then the batch and the detail. Add `--human`
for a table, `--schema` for every message's schema. Each run leaves a receipt
in `.parley/receipts/` (ignored by git). The contract is
`docs/topics/output/README.md`; what changed from 1.x is in `CHANGELOG.md`.

## Install a release

Each release has `taskalisk-v<version>.zip` and `SHA256SUMS`. The ZIP holds one
`taskalisk/` folder: the skill, its compiler, the bundled frontmatter and
threat models in `references/`, `LICENSE` and `NOTICE`, and a per-file
`SHA256SUMS`.

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

`skills/taskalisk/references/` holds symlinks, and `skills/taskalisk/LICENSE`
and `NOTICE` are symlinks to the files at the root. A checkout made without
symlink support, such as Git for Windows by default, shows them as one-line
files naming their targets; read `docs/` directly there. Release archives
always contain the documents themselves.

## Test

```sh
python3 -m unittest discover -s tests
```

The tests run offline. `tests/fake_gh.py` stands in for `gh` and logs every
call, so a test can check which repository each request went to. Every run in
the suite has each of its lines validated against its schema, and
`tests/fixtures/golden/` holds the 1.x output the lines must reconstruct.

The Rust rebuild ([decision 0001](docs/decisions/0001-rust-issue-dag-contract.md)) is a Cargo
workspace at the repository root. `crates/issue-dag-core` reads and validates `issue-dag/2`
documents and plans the graph and readiness over recorded observations, with no I/O;
`crates/issue-dag-bundle` reads an observation bundle into it. Together they run every document
and graph case of the vendored corpus. The toolchain is pinned in
`rust-toolchain.toml`, and CI runs the same three checks:

```sh
cargo fmt --all --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). The vendored Parley
writer, `skills/taskalisk/scripts/parley_emit.py`, is Apache-2.0 under its own
`parley_emit.LICENSE` and `parley_emit.NOTICE` beside it.
