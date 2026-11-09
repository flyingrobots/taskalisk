"""Require explicit issue-inventory identities and metadata shapes."""

from __future__ import annotations

import unittest

from fixture_inventory import inventory_issue

from skills.taskalisk.scripts.taskalisk_core.github_inventory_values import parse_inventory_issue


class GithubInventoryValues(unittest.TestCase):
    """No malformed issue metadata may become a plausible inventory summary."""

    def test_number_requires_a_positive_integer(self) -> None:
        """Booleans, strings and fractions are not issue identifiers."""
        for value in (None, True, 1.5, "7", 0, -7):
            row = inventory_issue()
            row["number"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "positive integer"):
                parse_inventory_issue(row)

    def test_title_and_url_require_text(self) -> None:
        """Missing or nontext display fields cannot silently become empty strings."""
        bad_values: tuple[object, ...] = (None, False, 0, [])
        for key in ("title", "url"):
            for value in bad_values:
                row = inventory_issue()
                row[key] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(TypeError, key):
                    parse_inventory_issue(row)
            row = inventory_issue()
            del row[key]
            with self.subTest(key=key), self.assertRaisesRegex(TypeError, key):
                parse_inventory_issue(row)

    def test_labels_require_an_array_of_named_objects(self) -> None:
        """A malformed later label cannot disappear or replace valid earlier labels."""
        empty: dict[str, object] = {}
        cases: tuple[tuple[object, str], ...] = (
            (None, "labels must be an array"),
            ("label", "labels must be an array"),
            (empty, "labels must be an array"),
            (["label"], "label must be an object"),
            ([empty], "label name"),
            ([{"name": "valid"}, {"name": False}], "label name"),
        )
        for value, diagnostic in cases:
            row = inventory_issue()
            row["labels"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex((TypeError, ValueError), diagnostic),
            ):
                parse_inventory_issue(row)
        row = inventory_issue()
        del row["labels"]
        with self.assertRaisesRegex(TypeError, "labels must be an array"):
            parse_inventory_issue(row)

    def test_milestone_requires_explicit_null_or_a_title(self) -> None:
        """A nullable milestone does not authorize falsey or missing metadata."""
        cases: tuple[tuple[object, str], ...] = (
            (False, "milestone must be an object"),
            ([], "milestone must be an object"),
            ({}, "milestone title"),
            ({"title": 0}, "milestone title"),
        )
        for value, diagnostic in cases:
            row = inventory_issue()
            row["milestone"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex((TypeError, ValueError), diagnostic),
            ):
                parse_inventory_issue(row)
        row = inventory_issue()
        del row["milestone"]
        with self.assertRaisesRegex(ValueError, "milestone field"):
            parse_inventory_issue(row)

    def test_valid_metadata_preserves_public_summary(self) -> None:
        """The issue summary retains ordered label names and a nullable milestone title."""
        row = inventory_issue()
        row.update(
            number=23,
            title="Plan",
            url="u",
            labels=[{"name": "a"}, {"name": "b"}],
            milestone={"title": "Release", "number": 3},
        )
        self.assertEqual(
            parse_inventory_issue(row),
            {
                "number": 23,
                "title": "Plan",
                "url": "u",
                "labels": ["a", "b"],
                "milestone": "Release",
            },
        )
        row.update(title="", url="", labels=[], milestone=None)
        self.assertEqual(
            parse_inventory_issue(row),
            {"number": 23, "title": "", "url": "", "labels": [], "milestone": None},
        )

    def test_root_requires_an_object(self) -> None:
        """A scalar or collection cannot represent an inventory issue."""
        bad_values: tuple[object, ...] = (None, False, [])
        for value in bad_values:
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "inventory issue must be an object"),
            ):
                parse_inventory_issue(value)
