"""Require checked fixture containers and scalar types before provider routing."""

from __future__ import annotations

import unittest

from fake_values import fields, integer, items, text


class FakeValues(unittest.TestCase):
    """Fixture admission rejects malformed configuration without coercing its meaning."""

    def test_objects_require_string_keys_and_preserve_unknown_values(self) -> None:
        """A container check does not invent types for the values it contains."""
        cases: tuple[object, ...] = (None, [], "text", {1: "bad"})
        for value in cases:
            with self.subTest(value=value), self.assertRaisesRegex(TypeError, "fixture object"):
                fields(value)
        self.assertEqual(fields({"body": [None, 2]}), {"body": [None, 2]})

    def test_arrays_require_lists_and_preserve_unknown_members(self) -> None:
        """Strings and mappings cannot silently become iterable fixture rows."""
        cases: tuple[object, ...] = (None, "text", {})
        for value in cases:
            with self.subTest(value=value), self.assertRaisesRegex(TypeError, "fixture array"):
                items(value)
        self.assertEqual(items([None, {"number": 2}]), [None, {"number": 2}])

    def test_text_is_not_inferred_from_truthiness_or_stringification(self) -> None:
        """Only actual text, including the empty string, reaches text-only operations."""
        cases: tuple[object, ...] = (None, False, 0, [])
        for value in cases:
            with self.subTest(value=value), self.assertRaisesRegex(TypeError, "fixture text"):
                text(value)
        self.assertEqual([text(""), text("é")], ["", "é"])

    def test_numbers_require_exact_integers(self) -> None:
        """Boolean, textual and floating values must not be coerced into identifiers."""
        for value in (None, True, "1", 1.5):
            with self.subTest(value=value), self.assertRaisesRegex(TypeError, "fixture integer"):
                integer(value)
        self.assertEqual([integer(-1), integer(0), integer(2)], [-1, 0, 2])
