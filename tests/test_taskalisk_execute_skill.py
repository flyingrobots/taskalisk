"""skills/taskalisk-execute/SKILL.md: a static specification, checked structurally and offline."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "taskalisk-execute" / "SKILL.md"
THIS_TEST = pathlib.Path(__file__)
# Built from pieces so this file never contains a machine-local home path itself.
HOME_PATH = re.compile("|".join(["/" + "Users/", "/" + "home/", r"[A-Za-z]:\\" + "Users", "/" + "private/var"]))


def text():
    return SKILL.read_text(encoding="utf-8")


def frontmatter(markdown):
    match = re.match(r"---\n(.*?)\n---\n", markdown, re.S)
    if not match:
        raise AssertionError("no YAML frontmatter")
    fields, key = {}, None
    for line in match.group(1).splitlines():
        top = re.match(r"([a-z][a-z-]*):\s*(.*)$", line)
        if top:
            key = top.group(1)
            fields[key] = top.group(2).strip()
        elif key:
            fields[key] += " " + line.strip()
    return fields


def section(markdown, heading):
    match = re.search(r"(?ms)^## " + re.escape(heading) + r"\n(.*?)(?=^## |\Z)", markdown)
    if not match:
        raise AssertionError(f"missing section: {heading}")
    return " ".join(match.group(1).split())


class TaskaliskExecuteSkillTest(unittest.TestCase):
    def test_frontmatter_has_name_and_description(self):
        fields = frontmatter(text())
        self.assertEqual(fields.get("name"), "taskalisk-execute")
        self.assertGreater(len(fields.get("description", "").strip(">- ")), 40)

    def test_required_headings(self):
        body = text()
        for heading in ["Coordinator-assigned dispatch", "Worker lifecycle", "Review and merge gate",
                        "Stop conditions", "Trust gate", "Coordinator rules"]:
            section(body, heading)

    def test_coordinator_assignment_and_non_claim(self):
        s = section(text(), "Coordinator-assigned dispatch")
        for phrase in ["one coordinator", "open pull requests and branches", "assignment ledger"]:
            self.assertIn(phrase.lower(), s.lower())
        self.assertRegex(s, r"never a cross-repository lock")
        self.assertRegex(s, r"does not (reserve|enforce|claim)")

    def test_worktree_and_draft_pr_before_implementation(self):
        s = section(text(), "Worker lifecycle")
        for phrase in ["worktree", "default branch", "draft pull request", "Closes owner/repo#N",
                       "before implementation", "RED", "GREEN", "--body-file", "Test Plan"]:
            self.assertIn(phrase, s)

    def test_fresh_context_review_gate(self):
        s = section(text(), "Review and merge gate")
        self.assertRegex(s, r"fresh[- ]context")
        self.assertIn("different context from the author", s)
        self.assertIn("READY", s)
        self.assertRegex(s, r"(?i)before (you )?undraft")
        self.assertRegex(s, r"(?i)never review your own")

    def test_bounded_bot_review_wait(self):
        s = section(text(), "Review and merge gate")
        self.assertIn("10 minutes", s)
        self.assertRegex(s, r"log(ged)? (it |the timeout )?explicitly")
        self.assertRegex(s, r"never poll forever")

    def test_merge_gate_and_decision_issues(self):
        s = section(text(), "Review and merge gate")
        for phrase in ["green CI", "zero unresolved review threads", ".type: decision",
                       "human sign-off", "never auto-merged"]:
            self.assertIn(phrase, s)

    def test_recompile_after_merge(self):
        s = section(text(), "Coordinator rules")
        self.assertRegex(s, r"[Rr]ecompile the DAG after every merge")
        self.assertRegex(s, r"never choose the next task from a stale compile")

    def test_stop_conditions(self):
        s = section(text(), "Stop conditions")
        for phrase in ["untrusted", "CHANGES_REQUIRED", "REFERRAL", "CI has failed"]:
            self.assertIn(phrase, s)

    def test_trust_gate_doctrine(self):
        s = section(text(), "Trust gate")
        self.assertRegex(s, r"data, not instructions")
        self.assertIn("source.untrusted_issues", s)

    def test_coordinator_lessons(self):
        s = section(text(), "Coordinator rules")
        for phrase in ["home repository", ".meters", "one at a time", "merge the default branch",
                       "never rebase", "conflict markers", "dismiss", "Propose, then apply",
                       "pre-existing failure", "workers do not merge"]:
            self.assertIn(phrase.lower(), s.lower())

    def test_no_machine_local_paths(self):
        for path in (SKILL, THIS_TEST):
            self.assertIsNone(HOME_PATH.search(path.read_text(encoding="utf-8")), str(path))

    def test_skill_is_not_in_the_release_payload(self):
        # Releasing a ZIP is out of scope (#67): the packager enumerates only skills/taskalisk/.
        self.assertIn('SKILL = "skills/taskalisk/"', (ROOT / "scripts" / "build_skill_release.py").read_text())


if __name__ == "__main__":
    unittest.main()
