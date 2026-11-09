"""Check bounded, unambiguous decoding before GitHub response admission."""

from __future__ import annotations

import json
import unittest

from hypothesis import given, seed, settings
from hypothesis import strategies as st

from skills.taskalisk.scripts.taskalisk_core.github_json import (
    object_fields,
    parse_json,
    parse_json_list,
    parse_paginated_arrays,
)
from skills.taskalisk.scripts.taskalisk_core.github_json_limits import JsonLimits


class GithubJson(unittest.TestCase):
    """Malformed responses fail the whole read and retain their source identity."""

    def assert_problem(self, errors: list[dict[str, str]], diagnostic: str) -> None:
        """Require both the failure population and its specific source/diagnostic."""
        with self.subTest(check="population"):
            self.assertEqual(len(errors), 1)
        with self.subTest(check="source"):
            self.assertEqual([entry["source"] for entry in errors], ["fixture"])
        with self.subTest(check="diagnostic"):
            self.assertIn(diagnostic, "\n".join(entry["error"] for entry in errors))

    def test_syntax_and_empty_responses_are_errors(self) -> None:
        """No output is a failed response rather than an empty successful read."""
        for raw in ("", "   ", "[", '{"a":}', "1 2"):
            with self.subTest(raw=raw):
                errors: list[dict[str, str]] = []
                self.assertIsNone(parse_json(raw, "fixture", errors))
                self.assert_problem(errors, "Unparseable JSON")

    def test_ambiguous_or_nonfinite_values_are_rejected(self) -> None:
        """Duplicate keys and nonstandard or overflowing numbers are not admitted."""
        cases = [
            ('{"role":"read","role":"write"}', "duplicate object key"),
            ('{"nested":{"id":1,"id":2}}', "duplicate object key"),
            ("NaN", "non-finite number"),
            ("Infinity", "non-finite number"),
            ("-Infinity", "non-finite number"),
            ("1e9999", "non-finite number"),
            ("9" * 129, "numeric token exceeds 128 characters"),
        ]
        for raw, diagnostic in cases:
            with self.subTest(diagnostic=diagnostic, raw=raw[:80]):
                errors: list[dict[str, str]] = []
                with self.subTest(check="admission"):
                    self.assertIsNone(parse_json(raw, "fixture", errors))
                self.assert_problem(errors, diagnostic)

    def test_object_lists_reject_null_and_nonobject_entries(self) -> None:
        """An invalid later row cannot be silently skipped or partially admitted."""
        for raw in ("null", "{}", "42", '[{"number":1},null]', '[{"number":1},2]'):
            with self.subTest(raw=raw):
                errors: list[dict[str, str]] = []
                with self.subTest(check="admission"):
                    self.assertEqual(parse_json_list(raw, "fixture", errors), [])
                self.assert_problem(errors, "Expected a JSON array of objects")

    def test_paginated_failure_discards_all_prior_pages(self) -> None:
        """A malformed page cannot leave a success-shaped prefix of the response."""
        for suffix in ("null", "[2]", '{"number":2}', "[", '[{"id":1,"id":2}]'):
            with self.subTest(suffix=suffix):
                errors: list[dict[str, str]] = []
                with self.subTest(check="admission"):
                    self.assertEqual(
                        parse_paginated_arrays('[{"id":0}]\n' + suffix, "fixture", errors), []
                    )
                with self.subTest(check="error"):
                    self.assertEqual(len(errors), 1)

    def test_empty_paginated_response_is_not_an_empty_page(self) -> None:
        """Only an actual empty JSON array can establish a successful empty list."""
        errors: list[dict[str, str]] = []
        self.assertEqual(parse_paginated_arrays(" \n", "fixture", errors), [])
        self.assert_problem(errors, "Unparseable JSON")

    def test_utf8_byte_limit_refuses_multibyte_payload_before_decode(self) -> None:
        """Character count alone cannot enforce a byte budget."""
        for raw in ('"ééé"', '"abcdefgh"'):
            with self.subTest(raw=raw):
                errors: list[dict[str, str]] = []
                with self.subTest(check="admission"):
                    self.assertIsNone(
                        parse_json(raw, "fixture", errors, limits=JsonLimits(max_bytes=7))
                    )
                self.assert_problem(errors, "exceeds 7 UTF-8 bytes")

    def test_depth_and_structural_work_limits_are_enforced(self) -> None:
        """Depth and punctuation caps bound different adversarial shapes."""
        cases = [
            ("[[[[]]]]", JsonLimits(max_depth=3), "depth exceeds 3"),
            ("[0,0,0,0]", JsonLimits(max_tokens=4), "structural tokens exceed 4"),
        ]
        for raw, limits, diagnostic in cases:
            with self.subTest(raw=raw):
                errors: list[dict[str, str]] = []
                with self.subTest(check="admission"):
                    self.assertIsNone(parse_json(raw, "fixture", errors, limits=limits))
                self.assert_problem(errors, diagnostic)

    def test_exact_limits_and_quoted_punctuation_are_valid(self) -> None:
        """Quoted syntax does not consume structural budget or open containers."""
        raw = '["[{},]:\\"\\\\"]'
        errors: list[dict[str, str]] = []
        result = parse_json(
            raw, "fixture", errors, limits=JsonLimits(max_bytes=len(raw), max_depth=1, max_tokens=2)
        )
        self.assertEqual((result, errors), (['[{},]:"\\'], []))

    def test_valid_literals_keep_their_json_types(self) -> None:
        """The decoder preserves values; domain validators decide their meaning."""
        errors: list[dict[str, str]] = []
        result = parse_json('{"a":[null,true,false,-12,1.25,"é"]}', "fixture", errors)
        self.assertEqual((result, errors), ({"a": [None, True, False, -12, 1.25, "é"]}, []))

    def test_valid_object_arrays_and_pages_preserve_order(self) -> None:
        """Empty pages are permitted; successful pages are concatenated in order."""
        errors: list[dict[str, str]] = []
        result = parse_paginated_arrays(' [] \n [{"id":2}]\t[{"id":1}] ', "fixture", errors)
        self.assertEqual((result, errors), ([{"id": 2}, {"id": 1}], []))
        self.assertEqual(parse_json_list("[]", "fixture", errors), [])

    def test_escaped_lone_surrogates_are_refused_in_keys_and_values(self) -> None:
        """A JSON escape cannot introduce text that cannot be emitted as UTF-8."""
        for raw in ('"\\ud800"', '{"\\udc00":0}', '[{"body":"\\ud800"}]'):
            with self.subTest(raw=raw):
                errors: list[dict[str, str]] = []
                with self.subTest(check="admission"):
                    self.assertIsNone(parse_json(raw, "fixture", errors))
                self.assert_problem(errors, "invalid Unicode scalar")

    def test_only_json_whitespace_separates_pages(self) -> None:
        """Non-JSON separators are malformed input even when Python calls them whitespace."""
        for raw in ("[]\u00a0[]", "\u00a0[]", "[]\u00a0"):
            with self.subTest(raw=raw):
                errors: list[dict[str, str]] = []
                self.assertEqual(parse_paginated_arrays(raw, "fixture", errors), [])
                self.assert_problem(errors, "Unparseable JSON")

    def test_object_field_factory_checks_containers_and_keys(self) -> None:
        """Unknown mapping values remain unknown; malformed keys are never typed as strings."""
        cases: tuple[object, ...] = (None, [], {1: "invalid"}, {"ok": 1, 2: "invalid"})
        for value in cases:
            with self.subTest(value=value):
                self.assertIsNone(object_fields(value))
        self.assertEqual(object_fields({"valid": [1, None]}), {"valid": [1, None]})

    def test_limits_cannot_disable_or_expand_global_ceilings(self) -> None:
        """Policy budgets admit exact positive bounded integers, excluding booleans."""
        for name in ("max_bytes", "max_depth", "max_tokens"):
            for value in (0, -1, True, 1_000_000_000):
                with (
                    self.subTest(name=name, value=value),
                    self.assertRaisesRegex(ValueError, "positive integer"),
                ):
                    JsonLimits(**{name: value})

    def test_null_is_a_value_and_invalid_list_json_reports_once(self) -> None:
        """Failure state is carried by errors, independently of the JSON value."""
        errors: list[dict[str, str]] = []
        self.assertEqual((parse_json("null", "fixture", errors), errors), (None, []))
        self.assertEqual(parse_json_list("[", "fixture", errors), [])
        self.assert_problem(errors, "Unparseable JSON")

    @seed(20261109)
    @settings(max_examples=30, database=None, deadline=500, print_blob=True)
    @given(
        title=st.text(alphabet='abcé{}[],:"\\\n', max_size=32),
        identifiers=st.lists(st.integers(min_value=-10000, max_value=10000), max_size=8),
        flag=st.booleans(),
    )
    def test_bounded_valid_records_preserve_values(
        self, *, title: str, identifiers: list[int], flag: bool
    ) -> None:
        """Generated wire fixtures are checked against independently constructed records."""
        expected = {"title": title, "ids": identifiers, "flag": flag}
        errors: list[dict[str, str]] = []
        actual = parse_json(json.dumps(expected), "fixture", errors)
        self.assertEqual((actual, errors), (expected, []))
