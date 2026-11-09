"""Check REST field admission independently of provider routing and graph discovery."""

from __future__ import annotations

import unittest

from fixture_rest import rest_issue

from skills.taskalisk.scripts.taskalisk_core.github_issue_values import parse_rest_issue


class GithubIssueValues(unittest.TestCase):
    """Wire shapes must establish identities and scalar types without coercion."""

    def test_issue_number_requires_a_positive_integer(self) -> None:
        """Booleans, fractions and text cannot alias a real issue number."""
        for value in (None, True, 1.5, "1", 0, -1):
            row = rest_issue()
            row["number"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex((TypeError, ValueError), "positive integer"),
            ):
                parse_rest_issue(row)
        row = rest_issue()
        del row["number"]
        with self.assertRaisesRegex((TypeError, ValueError), "positive integer"):
            parse_rest_issue(row)

    def test_repository_identity_must_be_present_and_parseable(self) -> None:
        """A missing repository cannot silently fall back to the home repository."""
        for value in (None, False, "", "not-a-repository"):
            row = rest_issue()
            row["repository_url"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex((TypeError, ValueError), "repository_url"),
            ):
                parse_rest_issue(row)
        row = rest_issue()
        del row["repository_url"]
        with self.assertRaisesRegex((TypeError, ValueError), "repository_url"):
            parse_rest_issue(row)

    def test_required_text_fields_do_not_accept_missing_or_nontext(self) -> None:
        """Title, URL and association are checked even when their values are falsey."""
        for key in ("title", "html_url", "author_association"):
            bad_text: tuple[object, ...] = (None, False, 0, [])
            for value in bad_text:
                row = rest_issue()
                row[key] = value
                with (
                    self.subTest(key=key, value=value),
                    self.assertRaisesRegex((TypeError, ValueError), key),
                ):
                    parse_rest_issue(row)
            row = rest_issue()
            del row[key]
            with self.subTest(key=key), self.assertRaisesRegex((TypeError, ValueError), key):
                parse_rest_issue(row)

    def test_state_cannot_default_or_stringify_into_open(self) -> None:
        """Only the open/closed state domain reaches dependency satisfaction."""
        bad_states: tuple[object, ...] = (None, False, 0, "", "other", [])
        for value in bad_states:
            row = rest_issue()
            row["state"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex((TypeError, ValueError), "state"),
            ):
                parse_rest_issue(row)
        row = rest_issue()
        del row["state"]
        with self.assertRaisesRegex((TypeError, ValueError), "state"):
            parse_rest_issue(row)

    def test_author_requires_a_supported_typed_identity(self) -> None:
        """Unknown actors and malformed logins cannot inherit OWNER association."""
        cases: tuple[tuple[object, str], ...] = (
            ([], "user must be an object"),
            (False, "user must be an object"),
            ({}, "login"),
            ({"login": 1, "type": "User"}, "login"),
            ({"login": "", "type": "User"}, "login"),
            ({"login": "owner"}, "unsupported author actor type"),
            ({"login": "owner", "type": "Organization"}, "unsupported author actor type"),
            ({"login": "owner", "type": []}, "unsupported author actor type"),
        )
        for value, diagnostic in cases:
            row = rest_issue()
            row["user"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex((TypeError, ValueError), diagnostic),
            ):
                parse_rest_issue(row)
        row = rest_issue()
        del row["user"]
        with self.assertRaisesRegex((TypeError, ValueError), "user field"):
            parse_rest_issue(row)

    def test_optional_text_preserves_null_without_coercing_other_values(self) -> None:
        """Nullable body and state reason still reject falsey nontext values."""
        for key in ("body", "state_reason"):
            bad_text: tuple[object, ...] = (False, 0, [])
            for value in bad_text:
                row = rest_issue()
                row[key] = value
                with (
                    self.subTest(key=key, value=value),
                    self.assertRaisesRegex((TypeError, ValueError), key),
                ):
                    parse_rest_issue(row)
        row = rest_issue()
        row.update(body=None, state_reason=None, user=None)
        meta = parse_rest_issue(row)["meta"]
        self.assertEqual(
            {
                "body": meta["body"],
                "state_reason": meta["state_reason"],
                "author": meta["author"],
                "author_type": meta["author_type"],
            },
            {"body": "", "state_reason": None, "author": None, "author_type": None},
        )
        del row["body"]
        del row["state_reason"]
        self.assertEqual(parse_rest_issue(row)["meta"], meta)

    def test_pull_request_discriminator_uses_checked_key_presence(self) -> None:
        """An empty object is still a PR; null and false are malformed discriminators."""
        bad_prs: tuple[object, ...] = (None, False, "", [])
        for value in bad_prs:
            row = rest_issue()
            row["pull_request"] = value
            with (
                self.subTest(value=value),
                self.assertRaisesRegex((TypeError, ValueError), "pull_request"),
            ):
                parse_rest_issue(row)
        row = rest_issue()
        row["pull_request"] = {}
        self.assertTrue(parse_rest_issue(row)["pull_request"])
        self.assertFalse(parse_rest_issue(rest_issue())["pull_request"])

    def test_valid_fields_preserve_identity_metadata_and_bot_type(self) -> None:
        """Typed admission preserves the returned identity, including transfer targets."""
        row = rest_issue()
        row.update(
            number=7,
            repository_url="https://api.github.com/repos/Other/Project",
            state="CLOSED",
            state_reason="not_planned",
            body="task body",
            title="Title",
            html_url="https://github.com/Other/Project/issues/7",
            user={"login": "ci[bot]", "type": "Bot"},
            author_association="COLLABORATOR",
        )
        self.assertEqual(
            parse_rest_issue(row),
            {
                "reference": ("other/project", 7),
                "pull_request": False,
                "meta": {
                    "title": "Title",
                    "state": "closed",
                    "state_reason": "not_planned",
                    "body": "task body",
                    "html_url": "https://github.com/Other/Project/issues/7",
                    "author": "ci[bot]",
                    "author_type": "Bot",
                    "association": "COLLABORATOR",
                },
            },
        )
        self.assertEqual(parse_rest_issue(rest_issue())["meta"]["author_type"], "User")

    def test_root_requires_an_object(self) -> None:
        """A scalar or collection cannot stand in for the issue response."""
        bad_roots: tuple[object, ...] = (None, [], False)
        for value in bad_roots:
            with (
                self.subTest(value=value),
                self.assertRaisesRegex((TypeError, ValueError), "issue must be an object"),
            ):
                parse_rest_issue(value)
