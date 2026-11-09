"""Check ActorTrust behavior through the public CLI."""

from cli_fixture import ECHO, HOME, STRANGER, TrustFixture, fm, issue, plan_state
from fake_values import field, items, records, text


class ActorTrust(TrustFixture):
    """Check typed author and editor identities against the trust policy."""

    def test_allowlisted_login_is_trusted(self) -> None:
        """Allowlisted login is trusted."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", STRANGER]
        r = self.out(
            self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--trust", STRANGER)
        )
        self.assertEqual(self.untrusted_ids(r), [])
        self.assertFalse(self.node(r, f"{HOME}#1")["opaque"])

    def test_collaborator_check_trusts_an_editor(self) -> None:
        """Collaborator check trusts an editor."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", "carol"]
        state["collaborators"] = {HOME: ["carol"]}
        self.assertEqual(
            self.untrusted_ids(
                self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
            ),
            [],
        )

    def test_triage_collaborator_is_not_trusted(self) -> None:
        """Triage collaborator is not trusted."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", "carol"]
        state["collaborators"] = {HOME: {"carol": "triage"}}
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{HOME}#1", self.untrusted_ids(r))
        self.assertTrue(
            any(
                "below write" in text(why)
                for u in records(field(r, "source", "untrusted_issues"))
                for why in items(u["reasons"])
            )
        )

    def test_member_association_alone_is_not_trusted(self) -> None:
        """Member association alone is not trusted."""
        state = plan_state()
        state["issues"][f"{HOME}#77"] = issue(
            177, "Org member", fm(f"{HOME}#77"), options={"author": "pat", "association": "MEMBER"}
        )
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertIn(f"{HOME}#77", self.untrusted_ids(r))

    def test_names_compare_case_insensitively(self) -> None:
        """Names compare case insensitively."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", "Carol"]
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=["Partner/Lib#1"])
        state["issues"]["Partner/Lib#1"] = issue(
            4242,
            "Partner lib",
            fm("Partner/Lib#1"),
            options={"author": "pat", "association": "OWNER"},
        )
        p = self.run_dag(
            state,
            "--from-github",
            "--root",
            f"{HOME}#9",
            "--trust",
            "carol",
            "--trust-owner",
            "partner",
        )
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertEqual(self.untrusted_ids(r), [])

    def test_collaborator_check_that_cannot_run_exits_2(self) -> None:
        """Collaborator check that cannot run exits 2."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", "carol"]
        state["collaborators_forbidden"] = True
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertIn("collaborators/carol/permission", p.stdout)

    def test_codeowners_allowlists_per_repository(self) -> None:
        """CODEOWNERS admits its listed authors only in the corresponding repository."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", "carol"]
        state["codeowners"] = {
            HOME: {
                ".github/CODEOWNERS": "# owners\n* @carol @flyingrobots/core\ndocs/ docs@example.com\n"
            }
        }
        r = self.out(
            self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--trust-codeowners")
        )
        self.assertEqual(self.untrusted_ids(r), [])
        self.assertEqual(field(r, "source", "trust", "codeowners", HOME), ["carol"])
        self.assertEqual(
            field(r, "source", "trust", "codeowners_teams_not_expanded"),
            {HOME: ["flyingrobots/core"]},
        )
        # The allowlist is per repository: Carol owns nothing in ECHO.
        state["issues"][f"{ECHO}#5"]["editors"] = ["owner", "carol"]
        r = self.out(
            self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--trust-codeowners")
        )
        self.assertIn(f"{ECHO}#5", self.untrusted_ids(r))
        self.assertTrue(self.node(r, f"{ECHO}#5")["opaque"])

    def test_bot_author_is_untrusted_unless_allowlisted(self) -> None:
        """Bot author is untrusted unless allowlisted."""
        state = plan_state()
        state["issues"][f"{HOME}#77"] = issue(
            177,
            "Automated",
            fm(f"{HOME}#77"),
            options={"author": "deploy-bot", "association": "OWNER", "author_type": "Bot"},
        )
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertIn(f"{HOME}#77", self.untrusted_ids(r))
        r = self.out(self.run_dag(state, "--from-github", "--trust", "deploy-bot[bot]"))
        self.assertNotIn(f"{HOME}#77", self.untrusted_ids(r))

    def test_bot_editor_is_untrusted(self) -> None:
        """Bot editor is untrusted."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", {"login": "deploy-bot", "type": "Bot"}]
        state["collaborators"] = {
            HOME: ["deploy-bot"]
        }  # even write permission does not trust a bot
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{HOME}#1", self.untrusted_ids(r))
        self.assertTrue(
            any(
                "bot actors" in text(why)
                for u in records(field(r, "source", "untrusted_issues"))
                for why in items(u["reasons"])
            )
        )

    def test_bot_allowlist_matches_every_github_spelling(self) -> None:
        """The bot allowlist recognizes the REST, GraphQL and CLI spellings exercised here."""
        state = plan_state()
        state["issues"][f"{HOME}#77"] = issue(
            177,
            "Automated",
            fm(f"{HOME}#77"),
            options={"author": "deploy-bot[bot]", "association": "NONE", "author_type": "Bot"},
        )
        for spelling in ("deploy-bot[bot]", "app/deploy-bot"):
            r = self.out(self.run_dag(state, "--from-github", "--trust", spelling))
            self.assertNotIn(f"{HOME}#77", self.untrusted_ids(r), spelling)
        # The bare spelling names a human, not the app.
        r = self.out(self.run_dag(state, "--from-github", "--trust", "deploy-bot"))
        self.assertIn(f"{HOME}#77", self.untrusted_ids(r))

    def test_bot_editor_sharing_the_authors_login_is_still_checked(self) -> None:
        """A bot editor sharing the author's login still requires separate admission."""
        state = plan_state()
        state["issues"][f"{HOME}#1"].update(
            author="ci-worker",
            association="OWNER",
            editors=["ci-worker", {"login": "ci-worker", "type": "Bot"}],
        )
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{HOME}#1", self.untrusted_ids(r))

    def test_allowlisting_a_bot_does_not_trust_a_human_with_the_same_login(self) -> None:
        """Allowlisting a bot does not trust a human with the same login."""
        state = plan_state()
        state["issues"][f"{HOME}#78"] = issue(
            178,
            "Impostor",
            fm(f"{HOME}#78"),
            options={"author": "ci-worker", "association": "NONE", "author_type": "User"},
        )
        r = self.out(self.run_dag(state, "--from-github", "--trust", "ci-worker[bot]"))
        self.assertIn(f"{HOME}#78", self.untrusted_ids(r))
        self.assertNotIn(
            f"{HOME}#78", [b["id"] for b in records(r["conflict_free_frontier_batch"])]
        )

    def test_association_only_counts_inside_the_scope(self) -> None:
        """Association only counts inside the scope."""
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=["mallory/trap#1"])
        state["issues"]["mallory/trap#1"] = issue(
            31337,
            "Trap",
            fm("mallory/trap#1"),
            options={"author": STRANGER, "association": "OWNER"},
        )
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        r = self.out(p)
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(
            any(
                "outside the trusted repositories" in text(v)
                for v in items(field(r, "frontmatter", "violations", f"{HOME}#1"))
            )
        )
        self.assertNotIn(["api", "repos/mallory/trap/issues/1"], self.calls())
