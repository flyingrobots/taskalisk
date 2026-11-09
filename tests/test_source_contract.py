"""Preserve observable identity parsing and roadmap ordering during decomposition."""

import unittest

from skills.taskalisk.scripts.taskalisk_core.graph import compile_and_analyze_dag
from skills.taskalisk.scripts.taskalisk_core.identities import parse_codeowners
from skills.taskalisk.scripts.taskalisk_core.rendering import render_roadmap_block


class SourceContract(unittest.TestCase):
    """Named examples distinguish deduplication, ordering and escaped display text."""

    def test_codeowners_separates_teams_and_logins_without_reordering_teams(self) -> None:
        """Duplicate teams remain one report entry and never become trusted logins."""
        owners = (
            "# @ignored\n* @Zoë @org/zeta @org/alpha @Zoë\n"
            "docs/ @org/zeta docs@example.invalid @ # @ignored\n"
        )
        self.assertEqual(parse_codeowners(owners), ({"Zoë"}, ["org/zeta", "org/alpha"]))

    def test_roadmap_groups_streams_and_sorts_qualified_issue_numbers(self) -> None:
        """A downstream task belongs in its stream, with escaped title and numeric ordering."""
        plan = compile_and_analyze_dag(
            set(),
            {
                "org/repo#10": {"title": "Ten", "workstream": "zeta"},
                "org/repo#2": {
                    "title": "Two [x] | <tag>",
                    "workstream": "zeta",
                    "depends_on": ["org/repo#10"],
                },
                "org/other#1": {"title": "One", "workstream": "alpha"},
                "org/repo#3": {"title": "Three"},
            },
        )
        if "error" in plan:
            self.fail(plan)
        result = render_roadmap_block(plan)
        checklist = result.split("## Task Checklist by Workstream (`area:*`)\n", 1)
        self.assertEqual(len(checklist), 2, result)
        self.assertEqual(
            checklist[1].split("## Transitively-Reduced Dependency DAG", 1)[0],
            "\n### alpha\n\n- [ ] org/other#1 One\n\n"
            "### unassigned\n\n- [ ] org/repo#3 Three\n\n"
            "### zeta\n\n- [ ] org/repo#2 Two \\[x\\] \\| &lt;tag&gt;\n"
            "- [ ] org/repo#10 Ten\n\n",
        )
