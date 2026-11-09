"""Check frontmatter refusal, normalization and preservation contracts directly."""

from __future__ import annotations

import unittest

from hypothesis import given, seed, settings
from hypothesis import strategies as st

from skills.taskalisk.scripts.taskalisk_core.frontmatter import (
    parse_frontmatter,
    rewrite_blocked_by,
    validate_frontmatter,
)
from skills.taskalisk.scripts.taskalisk_core.frontmatter_values import FieldValue, ParsedFields


def task_fields() -> ParsedFields:
    """Supply the validator's documented parsed-field input independently."""
    return {
        ".dag": "issue-dag/2",
        ".id": "org/repo#1",
        ".kind": "task",
        ".type": "feature",
        ".blocked_by": [],
    }


def task_body() -> str:
    """Build a fixed source fixture for rewrite contracts."""
    fields = {
        ".dag": "issue-dag/2",
        ".id": "org/repo#1",
        ".kind": "task",
        ".type": "feature",
        ".blocked_by": "[]",
    }
    lines = [f"{key}: {value}" for key, value in fields.items()]
    return "```yaml\n" + "\n".join(lines) + "\n```\n\nBody.\n"


class FrontmatterContract(unittest.TestCase):
    """Invalid fields fail visibly, and rewriting preserves unrelated text."""

    def violations(self, fields: ParsedFields) -> list[str]:
        """Read violations at the validator's parsed-field contract boundary."""
        _, violations, _ = validate_frontmatter(fields, ("org/repo", 1))
        return violations

    def test_invalid_field_values_have_specific_refusals(self) -> None:
        """Each format constraint has a discriminating negative example."""
        cases: list[tuple[str, FieldValue, str]] = [
            (".id", "#1", "must be owner/repo#N"),
            (".blocked_by", "nope", ".blocked_by must be a list"),
            (".blocked_by", ["org/repo#1"], ".blocked_by: self reference"),
            (".children", [], "a task must not have .children"),
            (".holds", "nope", ".holds must be a list"),
            (".holds", [""], ".holds must be a list"),
            (".meters", "nope", ".meters must be a list"),
            (".meters", ["ci*0"], ".meters: invalid entry"),
            (".status", "done", ".status must be active, parked, or blocked"),
            (".size_hours", 0, ".size_hours must be a positive integer"),
            (".size_hours", "eight", ".size_hours must be a positive integer"),
            (".kind", "unknown", ".kind must be task or container"),
            (".dag", "unknown", ".dag must be issue-dag/2"),
            (".type", "unknown", ".type must be one of"),
        ]
        for field, value, diagnostic in cases:
            with self.subTest(field=field, value=value):
                fields = task_fields()
                fields[field] = value
                self.assertIn(diagnostic, "\n".join(self.violations(fields)))

    def test_containers_need_children_and_cannot_have_blockers(self) -> None:
        """Container ownership is distinct from task dependency edges."""
        cases: list[tuple[ParsedFields, str]] = [
            ({".kind": "container"}, "a container needs .children"),
            (
                {".kind": "container", ".children": [], ".blocked_by": ["org/repo#2"]},
                "a container must not have .blocked_by",
            ),
        ]
        for overrides, diagnostic in cases:
            with self.subTest(overrides=overrides):
                fields = task_fields()
                fields.update(overrides)
                self.assertIn(diagnostic, self.violations(fields))

    def test_valid_resources_normalize_and_small_sizes_do_not_warn(self) -> None:
        """A permitted task retains sorted holds, meter counts and size."""
        fields = task_fields()
        fields.update(
            {".holds": ["src/", "docs/", "src/"], ".meters": ["ci", "io*2"], ".size_hours": 1}
        )
        record, violations, warnings = validate_frontmatter(fields, ("org/repo", 1))
        with self.subTest(check="admission"):
            self.assertEqual((violations, warnings), ([], []))
        with self.subTest(check="holds"):
            self.assertEqual(record["holds"], ["docs/", "src/"])
        with self.subTest(check="meters"):
            self.assertEqual(
                record["meters"], [{"name": "ci", "slots": 1}, {"name": "io", "slots": 2}]
            )

    def test_comments_blanks_quotes_and_integer_scalars(self) -> None:
        """The documented flat subset has deterministic scalar interpretation."""
        body = "```yaml\n# comment\n\nname: 'quoted'\ncount: 2\nitems: [1, 'two']\n```\n"
        self.assertEqual(
            parse_frontmatter(body), ({"name": "quoted", "count": 2, "items": ["1", "two"]}, [])
        )

    def test_duplicate_and_unterminated_fields_are_not_silently_accepted(self) -> None:
        """Malformed source carries specific parser diagnostics."""
        for body, diagnostic in [
            ("```yaml\nname: first\nname: second\n```\n", "duplicate key name"),
            ("```yaml\nitems: [broken\n```\n", "unterminated list for items"),
        ]:
            with self.subTest(diagnostic=diagnostic):
                _, problems = parse_frontmatter(body)
                self.assertIn(diagnostic, "\n".join(problems))

    def test_rewrite_refuses_absent_or_ambiguous_dependency_line(self) -> None:
        """Only one frontmatter dependency line is a supported rewrite target."""
        cases = [
            "No frontmatter.",
            task_body().replace(".blocked_by: []\n", ""),
            task_body().replace(".blocked_by: []", ".blocked_by: []\n.blocked_by: []"),
        ]
        for body in cases:
            with self.subTest(body=body):
                self.assertIsNone(rewrite_blocked_by(body, [("org/repo", 2)]))

    @seed(20261108)
    @settings(max_examples=30, database=None, deadline=500, print_blob=True)
    @given(
        st.lists(st.integers(min_value=2, max_value=100), min_size=1, max_size=8, unique=True),
        st.text(alphabet='abc 123|<>[]"\n', max_size=128),
    )
    def test_rewrite_changes_only_the_declared_dependency_line(
        self, numbers: list[int], prose: str
    ) -> None:
        """Bounded generated bodies preserve unrelated text byte for byte."""
        body = task_body() + "\n.blocked_by: []\n" + prose
        expected_line = (
            ".blocked_by: [" + ", ".join(f"org/repo#{number}" for number in numbers) + "]"
        )
        expected = body.replace(".blocked_by: []", expected_line, 1)
        actual = rewrite_blocked_by(body, [("org/repo", number) for number in numbers])
        self.assertEqual(actual, expected)
