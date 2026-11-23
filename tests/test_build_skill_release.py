"""scripts/build_skill_release.py: the release ZIP is self-contained, deterministic, checksummed, and built
only from tracked files at a committed revision."""
import hashlib
import importlib.util
import os
import pathlib
import posixpath
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_skill_release", ROOT / "scripts" / "build_skill_release.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)

GIT = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
       "-c", "init.defaultBranch=main"]
INLINE_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'(][^)]*)?\)")
REFERENCE_LINK = re.compile(r"(?m)^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+[\"'(].*)?$")


def relative_links(markdown):
    """Every relative link target in inline (with or without a title) and reference-style links."""
    targets = INLINE_LINK.findall(markdown) + REFERENCE_LINK.findall(markdown)
    return [t.split("#", 1)[0] for t in targets if not re.match(r"[a-z][a-z0-9+.-]*:", t) and not t.startswith("#")]


def make_repo(base, files, links=(), ignore=""):
    """A committed throwaway repository with a minimal skill. Returns its path."""
    repo = base / "repo"
    (repo / "skills" / "taskalisk" / "references").mkdir(parents=True)
    (repo / "docs").mkdir()
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    for path, target in links:
        (repo / path).symlink_to(target)
    if ignore:
        (repo / ".gitignore").write_text(ignore)
    subprocess.run(GIT + ["init", "-q", str(repo)], check=True)
    subprocess.run(GIT + ["-C", str(repo), "add", "-A"], check=True)
    subprocess.run(GIT + ["-C", str(repo), "commit", "-q", "-m", "fixture"], check=True)
    return repo


BASIC = {"skills/taskalisk/SKILL.md": "See [model](references/model.md).\n", "docs/model.md": "the model\n"}
MODEL_LINK = ("skills/taskalisk/references/model.md", "../../../docs/model.md")


class BuildSkillReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def members(self, archive):
        with zipfile.ZipFile(archive) as bundle:
            return {info.filename: (bundle.read(info), info.external_attr >> 16, info.date_time)
                    for info in bundle.infolist()}

    def test_two_builds_are_byte_identical(self):
        first = builder.build(ROOT, self.out / "a", "1.0.0")
        second = builder.build(ROOT, self.out / "b", "1.0.0")
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_separate_processes_with_different_hash_seeds_build_identical_bytes(self):
        digests = set()
        for seed in ("1", "2", "3"):
            out = self.out / f"seed{seed}"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "build_skill_release.py"), "--version", "1.0.0",
                            "--out", str(out)], check=True, capture_output=True, env=dict(os.environ, PYTHONHASHSEED=seed))
            digests.add(hashlib.sha256((out / "taskalisk-v1.0.0.zip").read_bytes()).hexdigest())
        self.assertEqual(len(digests), 1)

    def test_entries_carry_a_fixed_timestamp_not_the_clock_or_file_times(self):
        for name, (_, _, stamp) in self.members(builder.build(ROOT, self.out / "a", "1.0.0")).items():
            self.assertEqual(stamp, (1980, 1, 1, 0, 0, 0), name)

    def test_bundled_references_are_the_committed_repository_documents(self):
        members = self.members(builder.build(ROOT, self.out / "a", "1.0.0"))
        for doc in ("frontmatter-model.md", "threat-model.md"):
            data, mode, _ = members[f"taskalisk/references/{doc}"]
            committed = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:docs/{doc}"],
                                       capture_output=True, check=True).stdout
            self.assertEqual(data, committed)
            self.assertEqual(mode & 0o170000, 0o100000, f"{doc} must be a regular file, not a link")

    def test_link_extraction_covers_titles_and_reference_style(self):
        text = '[a](x.md) [b](y.md "title") [c](<z.md>) [d](https://e.example/f) [g](#h)\n[ref]: r.md "t"\n'
        self.assertEqual(relative_links(text), ["x.md", "y.md", "z.md", "r.md"])

    def test_every_relative_link_in_the_packaged_skill_resolves_inside_the_package(self):
        members = self.members(builder.build(ROOT, self.out / "a", "1.0.0"))
        skill = members["taskalisk/SKILL.md"][0].decode("utf-8")
        links = relative_links(skill)
        self.assertTrue(links, "SKILL.md should link its bundled references")
        for target in links:
            resolved = posixpath.normpath(posixpath.join("taskalisk", target))
            self.assertIn(resolved, members, f"SKILL.md links {target}, which the package lacks")

    def test_per_file_and_archive_checksums_verify(self):
        archive = builder.build(ROOT, self.out / "a", "1.0.0")
        members = self.members(archive)
        manifest = members.pop("taskalisk/SHA256SUMS")[0].decode("utf-8").splitlines()
        listed = dict(reversed(line.split("  ", 1)) for line in manifest)
        self.assertEqual(set(listed), {name[len("taskalisk/"):] for name in members})
        for name, digest in listed.items():
            self.assertEqual(hashlib.sha256(members[f"taskalisk/{name}"][0]).hexdigest(), digest)
        expected, name = (self.out / "a" / "SHA256SUMS").read_text().strip().split("  ", 1)
        self.assertEqual(name, "taskalisk-v1.0.0.zip")
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), expected)

    def test_the_compiler_keeps_its_executable_bit(self):
        members = self.members(builder.build(ROOT, self.out / "a", "1.0.0"))
        self.assertEqual(members["taskalisk/scripts/taskalisk.py"][1] & 0o777, 0o755)
        self.assertEqual(members["taskalisk/SKILL.md"][1] & 0o777, 0o644)

    def test_the_vendored_writer_and_the_schemas_ship_in_the_release(self):
        """OUT-17: the archive carries the pinned writer, listed in SHA256SUMS, and every schema as a regular file."""
        members = self.members(builder.build(ROOT, self.out / "a", "1.0.0"))
        pin = __import__("json").loads((ROOT / "skills" / "taskalisk" / "scripts" / "parley_emit.pin.json").read_text())
        data, mode, _ = members["taskalisk/scripts/parley_emit.py"]
        self.assertEqual(hashlib.sha256(data).hexdigest(), pin["sha256"])
        sums = members["taskalisk/SHA256SUMS"][0].decode("utf-8")
        self.assertIn(f"{pin['sha256']}  scripts/parley_emit.py\n", sums)
        for name in ("parley_emit.LICENSE", "parley_emit.NOTICE", "parley_emit.pin.json"):
            self.assertIn(f"taskalisk/scripts/{name}", members)
        schemas = sorted(n for n in members if n.startswith("taskalisk/schemas/"))
        self.assertEqual(len(schemas), len(list((ROOT / "skills" / "taskalisk" / "schemas").glob("*.schema.json"))))
        self.assertTrue(schemas)
        for name in schemas:
            self.assertEqual(members[name][1] & 0o170000, 0o100000, name)

    def test_existing_output_is_never_overwritten(self):
        (self.out / "a").mkdir()
        with self.assertRaises(FileExistsError):
            builder.build(ROOT, self.out / "a", "1.0.0")

    def test_version_must_be_a_release_number(self):
        for bad in ("1.0", "../1.0.0", "v1.0.0", "1.0.0/x", "1.0.0\n"):
            with self.assertRaises(ValueError):
                builder.build(ROOT, self.out / "a", bad)

    def test_a_failed_build_leaves_no_output_directory(self):
        with mock.patch.object(zipfile.ZipFile, "writestr", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                builder.build(ROOT, self.out / "a", "1.0.0")
        self.assertFalse((self.out / "a").exists())

    def test_untracked_files_in_the_skill_folder_are_not_packaged(self):
        repo = make_repo(self.out, BASIC, [MODEL_LINK])
        (repo / "skills" / "taskalisk" / "notes.txt").write_text("scratch\n")
        (repo / "skills" / "taskalisk" / "SKILL.md").write_text("uncommitted edit\n")
        members = self.members(builder.build(repo, self.out / "a", "1.0.0"))
        self.assertNotIn("taskalisk/notes.txt", members)
        self.assertEqual(members["taskalisk/SKILL.md"][0], BASIC["skills/taskalisk/SKILL.md"].encode())

    def test_a_checkout_without_symlinks_packages_the_documents(self):
        repo = make_repo(self.out, BASIC, [MODEL_LINK])
        clone = self.out / "clone"
        subprocess.run(GIT + ["-c", "core.symlinks=false", "clone", "-q", str(repo), str(clone)], check=True)
        self.assertFalse((clone / MODEL_LINK[0]).is_symlink(), "fixture should check out the link as a file")
        members = self.members(builder.build(clone, self.out / "a", "1.0.0"))
        self.assertEqual(members["taskalisk/references/model.md"][0], b"the model\n")

    def test_a_link_leaving_the_repository_is_refused(self):
        repo = make_repo(self.out, BASIC, [MODEL_LINK, ("skills/taskalisk/references/leak.md", "../../../../outside.txt")])
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            builder.build(repo, self.out / "a", "1.0.0")
        self.assertFalse((self.out / "a").exists())

    def test_a_link_into_a_sibling_sharing_the_repository_prefix_is_refused(self):
        (self.out / "repo-evil").mkdir()
        (self.out / "repo-evil" / "x.md").write_text("outside\n")
        repo = make_repo(self.out, BASIC, [MODEL_LINK, ("skills/taskalisk/references/x.md", "../../../../repo-evil/x.md")])
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            builder.build(repo, self.out / "a", "1.0.0")

    def test_a_link_to_another_link_is_refused(self):
        repo = make_repo(self.out, BASIC, [MODEL_LINK, ("docs/alias.md", "model.md"),
                                           ("skills/taskalisk/references/alias.md", "../../../docs/alias.md")])
        with self.assertRaisesRegex(ValueError, "not a regular file"):
            builder.build(repo, self.out / "a", "1.0.0")

    def test_a_committed_sha256sums_in_the_skill_is_refused(self):
        repo = make_repo(self.out, dict(BASIC, **{"skills/taskalisk/SHA256SUMS": "stale\n"}), [MODEL_LINK])
        with self.assertRaisesRegex(ValueError, "SHA256SUMS is written by the builder"):
            builder.build(repo, self.out / "a", "1.0.0")

    def test_a_link_through_a_directory_link_is_refused(self):
        files = dict(BASIC, **{"docs/deep/model.md": "the deep model\n"})
        links = [MODEL_LINK, ("skills/taskalisk/references/via", "../../../docs/deep"),
                 ("skills/taskalisk/references/odd.md", "via/../../../../docs/model.md")]
        repo = make_repo(self.out, files, links)
        with self.assertRaisesRegex(ValueError, "plain names, through no other link"):
            builder.build(repo, self.out / "a", "1.0.0")

    def test_links_to_git_metadata_or_ignored_files_are_refused(self):
        files = dict(BASIC, **{".env": "TOKEN=secret\n"})
        for name, target in (("config.md", "../../../.git/config"), ("env.md", "../../../.env")):
            with self.subTest(name):
                base = self.out / name
                base.mkdir()
                repo = make_repo(base, files, [MODEL_LINK, (f"skills/taskalisk/references/{name}", target)], ignore=".env\n")
                with self.assertRaisesRegex(ValueError, "not a tracked file"):
                    builder.build(repo, base / "a", "1.0.0")


if __name__ == "__main__":
    unittest.main()
