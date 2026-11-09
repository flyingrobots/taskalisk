"""Check PR admission independently of discovery and the provider double."""

from __future__ import annotations

import unittest

from fixture_pr import pull_request

from skills.taskalisk.scripts.taskalisk_core.github_pr_values import parse_pull_request


class GithubPrValues(unittest.TestCase):
    """Provider identities and trust fields need checked types, never coercion."""

    def test_pr_number_requires_a_positive_integer(self) -> None:
        """A Boolean, fraction or numeric string cannot identify a PR."""
        for value in (None, True, 1.5, "1", 0, -1):
            row = pull_request()
            row["number"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "PR number"):
                parse_pull_request(row)

    def test_required_text_fields_reject_missing_or_nontext(self) -> None:
        """Inventory display fields remain text even though they are not executable data."""
        bad_text: tuple[object, ...] = (None, False, 0, [])
        for key in ("title", "headRefName", "url"):
            for value in bad_text:
                row = pull_request()
                row[key] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(TypeError, key):
                    parse_pull_request(row)
            row = pull_request()
            del row[key]
            with self.subTest(key=key), self.assertRaisesRegex(TypeError, key):
                parse_pull_request(row)

    def test_trust_booleans_do_not_accept_truthy_or_falsey_substitutes(self) -> None:
        """Draft and foreign-branch evidence require actual Boolean values."""
        bad_booleans: tuple[object, ...] = (0, "false", [])
        for key in ("isDraft", "isCrossRepository"):
            for value in bad_booleans:
                row = pull_request()
                row[key] = value
                with self.subTest(key=key, value=value), self.assertRaisesRegex(TypeError, key):
                    parse_pull_request(row)
        row = pull_request()
        del row["isDraft"]
        with self.assertRaisesRegex(TypeError, "isDraft"):
            parse_pull_request(row)

    def test_author_requires_typed_login_and_bot_evidence(self) -> None:
        """A present author object must not silently inherit human classification."""
        cases: tuple[tuple[object, str], ...] = (
            ([], "author must be an object"),
            (False, "author must be an object"),
            ({}, "login"),
            ({"login": "", "is_bot": False}, "login"),
            ({"login": 1, "is_bot": False}, "login"),
            ({"login": "owner"}, "is_bot"),
            ({"login": "owner", "is_bot": 0}, "is_bot"),
            ({"login": "owner", "is_bot": "false"}, "is_bot"),
        )
        for value, diagnostic in cases:
            row = pull_request()
            row["author"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex((TypeError, ValueError), diagnostic),
            ):
                parse_pull_request(row)

    def test_closing_references_require_complete_qualified_identities(self) -> None:
        """Malformed references cannot be skipped or redirected to the home repository."""
        good_repo = {"name": "geordi", "owner": {"login": "flyingrobots"}}
        empty: dict[str, object] = {}
        cases: tuple[tuple[object, str], ...] = (
            (None, "closingIssuesReferences"),
            (empty, "closingIssuesReferences"),
            ([None], "closing issue must be an object"),
            ([{"number": True, "repository": good_repo}], "closing issue number"),
            ([{"number": "1", "repository": good_repo}], "closing issue number"),
            ([{"number": 1}], "closing repository"),
            ([{"number": 1, "repository": empty}], "closing repository owner"),
            ([{"number": 1, "repository": {"owner": {"login": "x"}}}], "repository name"),
            (
                [{"number": 1, "repository": {"name": "x/y", "owner": {"login": "z"}}}],
                "repository identity",
            ),
            (
                [{"number": 1, "repository": {"name": "x", "owner": {"login": "z/other"}}}],
                "repository identity",
            ),
        )
        for value, diagnostic in cases:
            row = pull_request()
            row["closingIssuesReferences"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex((TypeError, ValueError), diagnostic),
            ):
                parse_pull_request(row)

    def test_missing_or_null_trust_evidence_remains_unknown(self) -> None:
        """Absence cannot authorize a PR and does not invent a provider error."""
        row = pull_request()
        row.update(author=None, isCrossRepository=None)
        parsed = parse_pull_request(row)
        self.assertEqual((parsed["author"], parsed["cross_repository"]), (None, None))
        del row["author"]
        del row["isCrossRepository"]
        parsed = parse_pull_request(row)
        self.assertEqual((parsed["author"], parsed["cross_repository"]), (None, None))

    def test_valid_fields_preserve_identity_and_inventory_wire_values(self) -> None:
        """Checked linking data is canonical, while inventory metadata retains its shape."""
        row = pull_request()
        row.update(
            number=17,
            isDraft=True,
            isCrossRepository=True,
            author={"login": "app/build", "is_bot": True, "name": "Build", "id": "B_1"},
            closingIssuesReferences=[
                {
                    "number": 7,
                    "repository": {"name": "Project", "owner": {"login": "Other"}},
                    "id": "I_7",
                }
            ],
        )
        self.assertEqual(
            parse_pull_request(row),
            {
                "number": 17,
                "isDraft": True,
                "url": row["url"],
                "closes": [("other/project", 7)],
                "author": {"login": "app/build", "type": "Bot"},
                "cross_repository": True,
                "wire": row,
            },
        )
        self.assertEqual(
            parse_pull_request(pull_request())["author"], {"login": "owner", "type": "User"}
        )

    def test_empty_closing_list_and_display_text_are_valid(self) -> None:
        """A PR with no closing links contributes no dependency evidence."""
        row = pull_request()
        row.update(closingIssuesReferences=[], title="", headRefName="", url="")
        self.assertEqual(parse_pull_request(row)["closes"], [])

    def test_root_requires_an_object(self) -> None:
        """A scalar or collection cannot stand in for a PR row."""
        bad_roots: tuple[object, ...] = (None, [], False)
        for value in bad_roots:
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "PR must be an object"),
            ):
                parse_pull_request(value)
