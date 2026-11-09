"""Verify that the offline provider honors the edit-history request boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import cast

from cli_fixture import FAKE_GH, Harness, issue
from fixture_models import EditorValue

QUERY = (
    "query($owner:String!,$name:String!,$number:Int!,$after:String){"
    "repository(owner:$owner,name:$name){issue(number:$number){body "
    "userContentEdits(first:100,after:$after){pageInfo{hasNextPage endCursor} "
    "nodes{editor{login __typename}}}}}}"
)


class FakeGh(Harness):
    """A test double cannot be more generous than the API contract it simulates."""

    def run_fake(self, state: object, after: str | None = None) -> subprocess.CompletedProcess[str]:
        """Invoke the actual fixture provider with a fixed query and a five-second deadline."""
        self.state.write_text(json.dumps(state), encoding="utf-8")
        arguments = [
            sys.executable,
            str(FAKE_GH),
            "api",
            "graphql",
            "-f",
            f"query={QUERY}",
            "-f",
            "owner=org",
            "-f",
            "name=repo",
            "-F",
            "number=1",
        ]
        if after is not None:
            arguments.extend(["-f", f"after={after}"])
        environment = dict(os.environ, FAKE_GH_STATE=str(self.state), FAKE_GH_LOG=str(self.log))
        # policy-exception: PY-FAKE-PROVIDER-ARGV -- Fixed Python and provider path, without a shell.
        return subprocess.run(  # noqa: S603
            arguments, capture_output=True, text=True, env=environment, timeout=5, check=False
        )

    def field(self, value: object, *keys: str) -> object:
        """Inspect response containers without importing production admission code."""
        for key in keys:
            self.assertIsInstance(value, dict)
            # The assertion checks the container; it makes no claim about its members.
            fields = cast("dict[object, object]", value)
            self.assertIn(key, fields)
            value = fields[key]
        return value

    def test_default_page_honors_first_one_hundred(self) -> None:
        """The 101st editor requires another page, matching the actual GraphQL request."""
        editors: list[EditorValue] = ["owner"] * 101
        state = {
            "issues": {
                "org/repo#1": issue(
                    1,
                    "Task",
                    "Body",
                    options={
                        "editors": editors,
                    },
                )
            }
        }
        result = self.run_fake(state)
        self.assertEqual(result.returncode, 0, result.stderr)
        response: object = json.loads(result.stdout)
        edits = self.field(response, "data", "repository", "issue", "userContentEdits")
        nodes = self.field(edits, "nodes")
        self.assertIsInstance(nodes, list)
        # Only the asserted list container is claimed; node values remain unknown.
        values = cast("list[object]", nodes)
        with self.subTest(check="count"):
            self.assertEqual(len(values), 100)
        with self.subTest(check="continuation"):
            expected = True
            self.assertIs(self.field(edits, "pageInfo", "hasNextPage"), expected)
        with self.subTest(check="cursor"):
            self.assertEqual(self.field(edits, "pageInfo", "endCursor"), "100")
        last = self.run_fake(state, after="100")
        self.assertEqual(last.returncode, 0, last.stderr)
        final: object = json.loads(last.stdout)
        final_edits = self.field(final, "data", "repository", "issue", "userContentEdits")
        with self.subTest(check="last-record"):
            self.assertEqual(
                self.field(final_edits, "nodes"),
                [
                    {"editor": {"login": "owner", "__typename": "User"}},
                ],
            )
        with self.subTest(check="terminal"):
            expected = False
            self.assertIs(self.field(final_edits, "pageInfo", "hasNextPage"), expected)

    def test_page_override_cannot_disable_or_expand_the_request_limit(self) -> None:
        """A fixture error must fail explicitly instead of hiding pagination obligations."""
        for value in (0, -1, True, 101):
            with self.subTest(value=value):
                result = self.run_fake(
                    {
                        "issues": {"org/repo#1": issue(1, "Task", "Body")},
                        "edits_page_size": value,
                    }
                )
                with self.subTest(check="exit"):
                    self.assertEqual(result.returncode, 1)
                with self.subTest(check="diagnostic"):
                    self.assertIn(
                        "fake gh: edits_page_size must be an integer from 1 to 100", result.stderr
                    )
