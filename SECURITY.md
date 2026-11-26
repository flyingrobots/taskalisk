# Security

Taskalisk reads issue and pull request text from public repositories, so anyone can put text in front
of it. The threat model and the binding security policy are in
[docs/threat-model.md](docs/threat-model.md): what an attacker can do, each control, and whether it
is implemented (with a test), planned (with the issue that owes it) or policy.

## Reporting

Report a vulnerability privately through GitHub's **Report a vulnerability** form on this
repository's Security tab. Do not open a public issue for it. Say which control (by its label, such
as `C4` or `C14`) it defeats, or which threat (`T04b`) it realises, and give the smallest input
that shows it: an issue body, a fake-`gh` state, or a command line.

A fix lands with a test that fails without it, and the threat model's status for that control is
updated in the same pull request.

## Supported versions

Only the latest release is supported. The skill installs from a release ZIP; see the
[README](README.md).
