"""skills/taskalisk/templates/issue/: the canonical issue templates, checked against the compiler itself.

Oracle: an issue filed from a template is what GitHub stores, which is the template with its
`name/about/labels` header removed. That body must compile under the same parser and validator the
compiler runs on live issues, once the filer replaces NEW with the number GitHub assigned.
"""
import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "skills" / "taskalisk" / "templates" / "issue"
SCRIPT = ROOT / "skills" / "taskalisk" / "scripts" / "taskalisk.py"
# The seven task types the frontmatter model defines (docs/frontmatter-model.md, `.type`).
TYPES = ["feature", "bug", "decision", "research", "investigation", "spike", "task"]
SELF = ("example-owner/example-repo", 7)


def compiler():
    spec = importlib.util.spec_from_file_location("taskalisk_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def filed_body(name):
    """The issue body GitHub stores: the template without its header, NEW replaced by the issue number."""
    text = (TEMPLATES / f"{name}.md").read_text(encoding="utf-8")
    match = re.match(r"---\n.*?\n---\n", text, re.S)
    if not match:
        raise AssertionError(f"{name}.md has no GitHub template header")
    return text[match.end():].lstrip("\n").replace("OWNER/REPO#NEW", f"{SELF[0]}#{SELF[1]}")


class IssueTemplatesTest(unittest.TestCase):
    def test_one_template_per_task_type(self):
        self.assertEqual(sorted(p.stem for p in TEMPLATES.glob("*.md")), sorted(TYPES))

    def test_filed_template_compiles_as_a_valid_task(self):
        tk = compiler()
        for name in TYPES:
            with self.subTest(template=name):
                fields, problems = tk.parse_frontmatter(filed_body(name))
                self.assertIsNotNone(fields, f"{name}: no frontmatter block found")
                self.assertEqual(problems, [], f"{name}: parse problems")
                record, violations, _ = tk.validate_frontmatter(fields, SELF)
                self.assertEqual(violations, [], f"{name}: validation violations")
                self.assertEqual(record.get("type") or fields[".type"], name)

    def test_unfilled_template_names_no_real_issue(self):
        # A template filed without replacing NEW must fail, not compile as some other issue.
        tk = compiler()
        text = (TEMPLATES / "feature.md").read_text(encoding="utf-8")
        body = text[re.match(r"---\n.*?\n---\n", text, re.S).end():]
        fields, _ = tk.parse_frontmatter(body.lstrip("\n"))
        _, violations, _ = tk.validate_frontmatter(fields, SELF)
        self.assertNotEqual(violations, [])

    def test_templates_are_generic(self):
        # Deny by default: no project, owner, runtime or machine-local path may appear.
        forbidden = re.compile(r"(?i)parley|flyingrobots|\bbun\b|/" + "Users/|/" + "home/")
        files = sorted(TEMPLATES.iterdir())
        self.assertEqual(len(files), len(TYPES) + 1, "seven templates and config.yml")
        for path in files:
            with self.subTest(file=path.name):
                self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")))

    def test_every_template_opens_with_the_writing_tasks_sections_in_order(self):
        # Oracle: the "Body sections" table of skills/taskalisk/WRITING-TASKS.md, read from the file.
        guide = (ROOT / "skills" / "taskalisk" / "WRITING-TASKS.md").read_text(encoding="utf-8")
        table = re.search(r"(?ms)^## Body sections\n(.*?)(?=^## )", guide).group(1)
        required = re.findall(r"(?m)^\| ([A-Z][^|]*?) \| ", table)[1:]  # drop the header row
        self.assertEqual(len(required), 6, f"WRITING-TASKS.md sections read: {required}")
        for name in TYPES:
            with self.subTest(template=name):
                headings = re.findall(r"(?m)^## (.+)$", filed_body(name))
                self.assertEqual(headings[:len(required)], required)

    def test_every_template_keeps_its_definition_of_done(self):
        for name in TYPES:
            with self.subTest(template=name):
                self.assertRegex(filed_body(name), r"(?m)^## [0-9]+\. Definition of Done$")


INSTALLED = ROOT / ".github" / "ISSUE_TEMPLATE"


def template_names(folder):
    """The template files in a folder, by name."""
    return sorted(p.name for p in folder.iterdir())

THIS_REPO = ("flyingrobots/taskalisk", 83)


class InstalledTemplatesTest(unittest.TestCase):
    """flyingrobots/taskalisk#83: this repository's issue forms are the canonical templates, installed with
    the skill's snippet (OWNER/REPO replaced by this repository), and cannot drift from them."""

    def test_the_installed_folder_holds_exactly_the_canonical_files(self):
        self.assertTrue(INSTALLED.is_dir(), ".github/ISSUE_TEMPLATE/ is missing")
        self.assertEqual(template_names(INSTALLED), template_names(TEMPLATES))

    def test_a_hidden_file_left_by_the_system_is_not_drift(self):
        """A `.DS_Store` that macOS writes into either folder is not a template; it must not fail the suite."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            (folder / "task.md").write_text("x")
            (folder / ".DS_Store").write_bytes(b"\x00\x01")
            self.assertEqual(template_names(folder), ["task.md"])

    def test_each_installed_file_is_its_canonical_template_for_this_repository(self):
        for name in template_names(TEMPLATES):
            canonical = TEMPLATES / name
            with self.subTest(canonical.name):
                installed = INSTALLED / canonical.name
                self.assertTrue(installed.is_file(), f"{canonical.name} is not installed")
                expected = canonical.read_text(encoding="utf-8").replace("OWNER/REPO#NEW", f"{THIS_REPO[0]}#NEW")
                self.assertEqual(installed.read_text(encoding="utf-8"), expected,
                                 f"{canonical.name} differs from its canonical template; reinstall it with the skill's snippet")

    def test_an_issue_filed_from_each_installed_form_compiles_as_a_valid_node(self):
        tk = compiler()
        for name in TYPES:
            with self.subTest(form=name):
                text = (INSTALLED / f"{name}.md").read_text(encoding="utf-8")
                match = re.match(r"---\n.*?\n---\n", text, re.S)
                self.assertIsNotNone(match, f"{name}.md has no GitHub template header")
                body = text[match.end():].lstrip("\n").replace(f"{THIS_REPO[0]}#NEW", f"{THIS_REPO[0]}#{THIS_REPO[1]}")
                fields, problems = tk.parse_frontmatter(body)
                self.assertEqual(problems, [], name)
                record, violations, _ = tk.validate_frontmatter(fields, THIS_REPO)
                self.assertEqual(violations, [], name)


if __name__ == "__main__":
    unittest.main()
