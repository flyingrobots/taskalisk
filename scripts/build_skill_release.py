#!/usr/bin/env python3
"""Build a deterministic release ZIP of the Taskalisk skill and its SHA-256 checksums.

The archive holds one `taskalisk/` folder: every file under `skills/taskalisk/`,
with the links under `references/` replaced by the repository documents they
name, plus a per-file `SHA256SUMS`. Identical source bytes give identical
archive bytes. The output directory must not exist; nothing is overwritten.

Usage: python3 scripts/build_skill_release.py --version 1.0.0 --out .runs/release-v1.0.0
"""
import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path("skills/taskalisk")
SKIPPED_PARTS = {"__pycache__", ".DS_Store"}
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?")


def payload(root):
    """Map each archive member name to (bytes, executable)."""
    root = root.resolve()
    skill = root / SKILL
    if not (skill / "SKILL.md").is_file():
        raise ValueError(f"{SKILL}/SKILL.md is missing")
    files = {}
    for source in sorted(skill.rglob("*")):
        relative = source.relative_to(skill)
        if SKIPPED_PARTS & set(relative.parts) or source.suffix == ".pyc":
            continue
        if source.is_dir() and not source.is_symlink():
            continue
        real = source.resolve()
        if root not in real.parents:
            raise ValueError(f"{relative} resolves outside the repository")
        if not real.is_file():
            raise ValueError(f"{relative} is not a regular file")
        files[relative.as_posix()] = (real.read_bytes(), bool(real.stat().st_mode & 0o111))
    return files


def build(root, destination, version):
    if not VERSION.fullmatch(version):
        raise ValueError("version must be a release number such as 1.0.0")
    files = payload(root)
    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, (data, _) in sorted(files.items()))
    files["SHA256SUMS"] = (manifest.encode("utf-8"), False)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination / f"taskalisk-v{version}.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as bundle:
        for name, (data, executable) in sorted(files.items()):
            entry = zipfile.ZipInfo(f"taskalisk/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (0o100755 if executable else 0o100644) << 16
            bundle.writestr(entry, data)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path, required=True, help="new output directory; never overwritten")
    args = parser.parse_args()
    try:
        archive = build(ROOT, args.out, args.version)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Release not built: {error}\n")
    print(archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
