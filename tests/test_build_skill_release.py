"""scripts/build_skill_release.py: the release ZIP is self-contained, deterministic and checksummed."""
import hashlib
import importlib.util
import pathlib
import posixpath
import re
import shutil
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_skill_release", ROOT / "scripts" / "build_skill_release.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)

LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


class BuildSkillReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def members(self, archive):
        with zipfile.ZipFile(archive) as bundle:
            return {info.filename: (bundle.read(info), info.external_attr >> 16) for info in bundle.infolist()}

    def test_two_builds_are_byte_identical(self):
        first = builder.build(ROOT, self.out / "a", "1.0.0")
        second = builder.build(ROOT, self.out / "b", "1.0.0")
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_bundled_references_are_the_repository_documents(self):
        members = self.members(builder.build(ROOT, self.out / "a", "1.0.0"))
        for doc in ("frontmatter-model.md", "threat-model.md"):
            data, mode = members[f"taskalisk/references/{doc}"]
            self.assertEqual(data, (ROOT / "docs" / doc).read_bytes())
            self.assertEqual(mode & 0o170000, 0o100000, f"{doc} must be a regular file, not a link")

    def test_every_relative_link_in_the_packaged_skill_resolves_inside_the_package(self):
        members = self.members(builder.build(ROOT, self.out / "a", "1.0.0"))
        names = set(members)
        skill = members["taskalisk/SKILL.md"][0].decode("utf-8")
        links = [t for t in LINK.findall(skill) if not re.match(r"[a-z]+:", t)]
        self.assertTrue(links, "SKILL.md should link its bundled references")
        for target in links:
            resolved = posixpath.normpath(posixpath.join("taskalisk", target))
            self.assertIn(resolved, names, f"SKILL.md links {target}, which the package lacks")

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

    def test_existing_output_is_never_overwritten(self):
        (self.out / "a").mkdir()
        with self.assertRaises(FileExistsError):
            builder.build(ROOT, self.out / "a", "1.0.0")

    def test_version_must_be_a_release_number(self):
        for bad in ("1.0", "../1.0.0", "v1.0.0", "1.0.0/x"):
            with self.assertRaises(ValueError):
                builder.build(ROOT, self.out / "a", bad)

    def test_a_link_leaving_the_repository_is_refused(self):
        repo = self.out / "repo"
        shutil.copytree(ROOT / "skills", repo / "skills", symlinks=True)
        shutil.copytree(ROOT / "docs", repo / "docs")
        secret = self.out / "outside.txt"
        secret.write_text("not part of the repository\n")
        (repo / "skills" / "taskalisk" / "references" / "leak.md").symlink_to(secret)
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            builder.build(repo, self.out / "a", "1.0.0")
        self.assertFalse((self.out / "a").exists())


if __name__ == "__main__":
    unittest.main()
