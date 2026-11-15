#!/usr/bin/env python3
"""Build a deterministic release ZIP of the Taskalisk skill and its SHA-256 checksums.

The archive holds one `taskalisk/` folder: every file tracked under
`skills/taskalisk/` at a committed revision (`--ref`, default HEAD), with each
link replaced by the tracked file it names, plus a per-file `SHA256SUMS`. It is
built from Git's record, never from the working folder: untracked, ignored and
uncommitted files are not included, and a checkout without symlink support
builds the same archive. Identical revisions give identical archive bytes. The
output directory must not exist; nothing is overwritten.

Usage: python3 scripts/build_skill_release.py --version 1.0.0 --out .runs/release-v1.0.0 [--ref v1.0.0]
"""
import argparse
import hashlib
import posixpath
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = "skills/taskalisk/"
SKIPPED_PARTS = {"__pycache__", ".DS_Store"}
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?")
LINK_MODE, EXECUTABLE_MODE, FILE_MODE = "120000", "100755", "100644"


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(args[:2])} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def tracked(root, ref):
    """Map each tracked path at ref to (mode, object id)."""
    entries = {}
    for record in git(root, "ls-tree", "-r", "-z", "--full-tree", ref).split(b"\0"):
        if record:
            meta, path = record.split(b"\t", 1)
            mode, _, oid = meta.decode().split(" ")
            entries[path.decode("utf-8")] = (mode, oid)
    return entries


def plain_target(target):
    """Leading `..` steps, then plain names: text resolution then matches the checkout's."""
    parts = target.split("/")
    while parts and parts[0] == "..":
        parts.pop(0)
    return bool(parts) and all(part not in ("", ".", "..") for part in parts)


def passes_through_link(resolved, entries):
    parts = resolved.split("/")
    return any(entries.get("/".join(parts[:i]), ("",))[0] == LINK_MODE for i in range(1, len(parts)))


def payload(root, ref):
    """Map each archive member name to (bytes, executable)."""
    entries = tracked(root, ref)
    if SKILL + "SKILL.md" not in entries:
        raise ValueError(f"{SKILL}SKILL.md is not tracked at {ref}")
    files = {}
    for path in sorted(p for p in entries if p.startswith(SKILL)):
        relative = path[len(SKILL):]
        if SKIPPED_PARTS & set(relative.split("/")) or relative.endswith(".pyc"):
            continue
        if relative == "SHA256SUMS":
            raise ValueError("SHA256SUMS is written by the builder; remove the tracked one from the skill")
        mode, oid = entries[path]
        if mode == LINK_MODE:
            target = git(root, "cat-file", "blob", oid).decode("utf-8")
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
            if target.startswith("/") or resolved == ".." or resolved.startswith("../"):
                raise ValueError(f"{relative} resolves outside the repository")
            if not plain_target(target) or passes_through_link(resolved, entries):
                raise ValueError(f"{relative} must name its target as leading ../ steps and plain names, "
                                 "through no other link")
            if resolved not in entries:
                raise ValueError(f"{relative} names {resolved}, which is not a tracked file")
            mode, oid = entries[resolved]
            if mode not in (FILE_MODE, EXECUTABLE_MODE):
                raise ValueError(f"{relative} names {resolved}, which is not a regular file")
        elif mode not in (FILE_MODE, EXECUTABLE_MODE):
            raise ValueError(f"{relative} is not a regular file")
        files[relative] = (git(root, "cat-file", "blob", oid), mode == EXECUTABLE_MODE)
    return files


def build(root, destination, version, ref="HEAD"):
    if not VERSION.fullmatch(version):
        raise ValueError("version must be a release number such as 1.0.0")
    files = payload(root, ref)
    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, (data, _) in sorted(files.items()))
    files["SHA256SUMS"] = (manifest.encode("utf-8"), False)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination / f"taskalisk-v{version}.zip"
    sums = destination / "SHA256SUMS"
    try:
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as bundle:
            for name, (data, executable) in sorted(files.items()):
                entry = zipfile.ZipInfo(f"taskalisk/{name}", date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (0o100755 if executable else 0o100644) << 16
                bundle.writestr(entry, data)
        sums.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="utf-8")
    except BaseException:
        for created in (archive, sums):
            if created.exists():
                created.unlink()
        destination.rmdir()
        raise
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path, required=True, help="new output directory; never overwritten")
    parser.add_argument("--ref", default="HEAD", help="committed revision to package (default HEAD)")
    args = parser.parse_args()
    try:
        archive = build(ROOT, args.out, args.version, args.ref)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Release not built: {error}\n")
    print(archive)
    return 0


if __name__ == "__main__":
    sys.exit(main())
