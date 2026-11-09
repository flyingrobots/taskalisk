"""Check malformed edit-history fields through the real CLI and fake provider."""

from __future__ import annotations

import json
import subprocess
from typing import cast

from cli_fixture import Harness

BODY = "```yaml\n.dag: issue-dag/2\n.id: org/repo#1\n.kind: task\n.type: task\n.blocked_by: []\n```"
LAST_PAGE = {"hasNextPage": False, "endCursor": None}


def envelope(issue: object) -> dict[str, object]:
    """Construct the wire envelope independently of production admission code."""
    return {"data": {"repository": {"issue": issue}}}


def issue_with_edits(edits: object) -> dict[str, object]:
    """Keep the task body valid while varying only its edit-history connection."""
    return {"body": BODY, "userContentEdits": edits}


class GithubHistoryCli(Harness):
    """Malformed trust evidence is a run failure, not absent or trusted work."""

    def run_history(self, payload: object) -> subprocess.CompletedProcess[str]:
        """Override only the provider response; execute ordinary CLI admission."""
        return self.run_history_bytes(json.dumps(payload))

    def run_history_bytes(self, raw: str) -> subprocess.CompletedProcess[str]:
        """Supply exact provider bytes, including undecodable JSON."""
        state: dict[str, object] = {
            "home": "org/repo",
            "issues": {"org/repo#1": {"id": 1, "title": "Task", "state": "open", "body": BODY}},
            "blocked_by": {},
            "graphql_raw": raw,
        }
        return self.run_dag(state, "--from-github")

    def assert_refused(self, payload: object) -> None:
        """Require structured exit 2 and a history-specific failure diagnostic."""
        result = self.run_history(payload)
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        with self.subTest(check="structured"):
            self.assertTrue(result.stdout.startswith("{"), result.stdout + result.stderr)
            decoded: object = json.loads(result.stdout)
            self.assertIsInstance(decoded, dict)
            # assertIsInstance checks the container; values remain unknown.
            fields = cast("dict[object, object]", decoded)
            with self.subTest(check="refusal"):
                expected_ok = False
                self.assertIs(fields.get("ok"), expected_ok)
            with self.subTest(check="source"):
                problems = fields.get("github_errors")
                self.assertIsInstance(problems, list)
                # The assertion admits only the list container, not its entries.
                entries = cast("list[object]", problems)
                sources: list[object] = []
                for entry in entries:
                    self.assertIsInstance(entry, dict)
                    # The assertion admits only the dict container, not its fields.
                    problem = cast("dict[object, object]", entry)
                    sources.append(problem.get("source"))
                self.assertIn("gh api graphql (edit history of org/repo#1)", sources)
        with self.subTest(check="diagnostic"):
            self.assertIn("GraphQL", result.stdout)

    def test_nested_envelope_shapes_fail_closed(self) -> None:
        """Container checks precede every nested field access."""
        cases: tuple[object, ...] = (
            None,
            [],
            {"data": []},
            {"data": {"repository": [1]}},
            envelope([1]),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                self.assert_refused(payload)

    def test_body_requires_text_even_when_a_wrong_type_is_falsey(self) -> None:
        """A falsey malformed body must not masquerade as an empty issue."""
        cases: tuple[object, ...] = (None, False, 0, [], {})
        for body in cases:
            with self.subTest(body=body):
                self.assert_refused(
                    envelope(
                        {
                            "body": body,
                            "userContentEdits": {"nodes": [], "pageInfo": LAST_PAGE},
                        }
                    )
                )

    def test_connection_requires_nodes_and_pagination(self) -> None:
        """Missing pagination cannot establish that the editor list is complete."""
        cases: tuple[object, ...] = (
            None,
            [],
            {"nodes": []},
            {"nodes": {}, "pageInfo": LAST_PAGE},
            {"pageInfo": LAST_PAGE},
        )
        for edits in cases:
            with self.subTest(edits=edits):
                self.assert_refused(envelope(issue_with_edits(edits)))

    def test_page_info_has_exact_boolean_and_nullable_cursor_types(self) -> None:
        """Neither coercion nor a missing cursor is evidence of pagination progress."""
        cases: tuple[object, ...] = (
            None,
            [],
            {},
            {"hasNextPage": False},
            {"hasNextPage": 0, "endCursor": None},
            {"hasNextPage": "false", "endCursor": None},
            {"hasNextPage": False, "endCursor": 3},
            {"hasNextPage": True, "endCursor": None},
            {"hasNextPage": True, "endCursor": ""},
        )
        for page in cases:
            with self.subTest(page=page):
                self.assert_refused(envelope(issue_with_edits({"nodes": [], "pageInfo": page})))

    def test_actor_fields_cannot_collide_with_the_trusted_author(self) -> None:
        """Only checked User/Bot actors enter the current identity policy."""
        cases: tuple[object, ...] = (
            True,
            "text",
            {},
            {"editor": []},
            {"editor": {"login": 3, "__typename": "User"}},
            {"editor": {"login": "owner"}},
            {"editor": {"login": "owner", "__typename": None}},
            {"editor": {"login": "owner", "__typename": "Organization"}},
            {"editor": {"login": "owner", "__typename": "FutureActor"}},
        )
        for node in cases:
            with self.subTest(node=node):
                self.assert_refused(
                    envelope(
                        issue_with_edits(
                            {
                                "nodes": [node],
                                "pageInfo": LAST_PAGE,
                            }
                        )
                    )
                )

    def test_graphql_errors_cannot_admit_partial_data(self) -> None:
        """A response carrying GraphQL errors is not complete trust evidence."""
        payload = envelope(issue_with_edits({"nodes": [], "pageInfo": LAST_PAGE}))
        payload["errors"] = [{"message": "partial response"}]
        self.assert_refused(payload)

    def test_invalid_json_is_a_structured_run_error(self) -> None:
        """Decoder failure retains the source-specific history error envelope."""
        result = self.run_history_bytes("[")
        with self.subTest(check="exit"):
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        with self.subTest(check="diagnostic"):
            self.assertIn("Unparseable JSON", result.stdout)

    def test_repeated_cursor_is_refused_after_two_requests(self) -> None:
        """A provider repeating the same cursor cannot create an unbounded loop."""
        self.assert_refused(
            envelope(
                issue_with_edits(
                    {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": True, "endCursor": "same"},
                    }
                )
            )
        )
        self.assertEqual(self.log.read_text().count('"graphql"'), 2)

    def test_nullable_editor_remains_an_untrusted_identity(self) -> None:
        """Schema-permitted missing identity is preserved for the trust decision."""
        for node in (None, {"editor": None}):
            with self.subTest(node=node):
                result = self.run_history(
                    envelope(
                        issue_with_edits(
                            {
                                "nodes": [node],
                                "pageInfo": LAST_PAGE,
                            }
                        )
                    )
                )
                with self.subTest(check="exit"):
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                with self.subTest(check="trust"):
                    self.assertIn("editor (none): no login", result.stdout)

    def test_valid_user_and_empty_body_are_readable(self) -> None:
        """Ordinary history and a deliberately empty issue body remain valid."""
        for body in (BODY, ""):
            with self.subTest(body=body):
                result = self.run_history(
                    envelope(
                        {
                            "body": body,
                            "userContentEdits": {
                                "nodes": [{"editor": {"login": "owner", "__typename": "User"}}],
                                "pageInfo": LAST_PAGE,
                            },
                        }
                    )
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
