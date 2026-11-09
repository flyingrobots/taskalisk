"""Check DiscoveryTrust behavior through the public CLI."""

from cli_fixture import ECHO, HOME, STRANGER, TrustFixture, fm, issue, plan_state
from fake_values import field, fields, items, records


class DiscoveryTrust(TrustFixture):
    def test_untrusted_seed_is_listed_and_never_a_node(self):
        state = plan_state()
        state["issues"][f"{HOME}#77"] = issue(
            177, "Free money", fm(f"{HOME}#77"), options={"author": STRANGER, "association": "NONE"}
        )
        p = self.run_dag(state, "--from-github")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertNotIn(f"{HOME}#77", self.ids(r))
        self.assertNotIn(
            f"{HOME}#77", [b["id"] for b in records(r["conflict_free_frontier_batch"])]
        )
        entry = next(
            u for u in records(field(r, "source", "untrusted_issues")) if u["id"] == f"{HOME}#77"
        )
        self.assertEqual(entry["author"], STRANGER)
        self.assertNotIn("title", entry)

    def test_untrusted_seed_referenced_by_a_trusted_task_blocks_it(self):
        state = plan_state()
        state["issues"][f"{HOME}#77"] = issue(
            177, "Stranger", fm(f"{HOME}#77"), options={"author": STRANGER, "association": "NONE"}
        )
        state["issues"][f"{HOME}#2"]["body"] = fm(
            f"{HOME}#2", blocked_by=[f"{HOME}#1", f"{HOME}#77"]
        )
        p = self.run_dag(state, "--from-github")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertIn(f"{HOME}#77", items(self.node(r, f"{HOME}#2")["open_parents"]))
        self.assertTrue(self.node(r, f"{HOME}#77")["untrusted"])
        self.assertNotIn(
            f"{HOME}#77", [b["id"] for b in records(r["conflict_free_frontier_batch"])]
        )

    def test_untrusted_editor_makes_a_trusted_issue_an_opaque_blocker(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", STRANGER]
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{HOME}#1", self.untrusted_ids(r))
        node = self.node(r, f"{HOME}#1")
        self.assertTrue(node["opaque"] and node["untrusted"])
        self.assertEqual(node["title"], "(untrusted issue)")
        self.assertEqual(self.node(r, f"{HOME}#2")["open_parents"], [f"{HOME}#1"])
        self.assertNotIn(f"{HOME}#1", [b["id"] for b in records(r["conflict_free_frontier_batch"])])

    def test_null_edit_history_connection_exits_2(self):
        state = plan_state()
        state["graphql_null_edits"] = True
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        self.assertEqual(p.returncode, 2, p.stdout)

    def test_wrong_shape_issue_response_exits_2(self):
        state = plan_state()
        state["issue_get_returns_list"] = True
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        self.assertEqual(p.returncode, 2, p.stdout)

    def test_wrong_shape_listing_page_exits_2(self):
        state = plan_state()
        state["issues_list_returns_object"] = True
        p = self.run_dag(state, "--from-github")
        self.assertEqual(p.returncode, 2, p.stdout)

    def test_stranger_seed_costs_no_permission_lookup(self):
        state = plan_state()
        state["issues"][f"{HOME}#77"] = issue(
            177, "Flood", fm(f"{HOME}#77"), options={"author": STRANGER, "association": "NONE"}
        )
        self.run_dag(state, "--from-github")
        self.assertFalse(any("collaborators/mallory" in " ".join(c) for c in self.calls()))

    def test_mis_cased_reference_is_not_reported_as_transferred(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=["FlyingRobots/Echo#5"])
        state["issues"]["FlyingRobots/Echo#5"] = state["issues"].pop(f"{ECHO}#5")
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#1")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertNotIn(f"{HOME}#1", fields(field(r, "frontmatter", "violations")))

    def test_compare_mode_fails_closed_on_a_gh_error(self):
        state = plan_state()
        state["blocked_by_fail"] = True
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--compare-relationships")
        self.assertEqual(p.returncode, 2, p.stdout)

    def test_home_owner_with_capitals_compiles_and_links_prs(self):
        state = plan_state()
        state["home"] = "FlyingRobots/Geordi"
        state["issues"] = {
            k.replace(HOME, "FlyingRobots/Geordi"): v for k, v in state["issues"].items()
        }
        state["prs"] = [
            {
                "number": 8,
                "title": "Work",
                "headRefName": "task/work",
                "isDraft": False,
                "url": "u",
                "author": {"login": "owner", "is_bot": False},
                "isCrossRepository": False,
                "closingIssuesReferences": [
                    {
                        "number": 2,
                        "repository": {"name": "Geordi", "owner": {"login": "FlyingRobots"}},
                    }
                ],
            }
        ]
        state["collaborators"] = {"FlyingRobots/Geordi": ["owner"]}
        p = self.run_dag(state, "--from-github")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertEqual(field(r, "frontmatter", "violations"), {})
        self.assertEqual(self.node(r, f"{HOME}#2")["status"], "in-review")
        self.assertEqual(len([i for i in self.ids(r) if i.endswith("#2")]), 1)

    def test_stranger_seed_costs_no_edit_history_query(self):
        state = plan_state()
        state["issues"][f"{HOME}#77"] = issue(
            177, "Flood", fm(f"{HOME}#77"), options={"author": STRANGER, "association": "NONE"}
        )
        self.run_dag(state, "--from-github")
        graphql_calls = [
            c for c in self.calls() if c[:2] == ["api", "graphql"] and "number=77" in c
        ]
        self.assertEqual(graphql_calls, [])

    def test_parsed_body_is_the_one_whose_editors_were_checked(self):
        state = plan_state()
        state["issues"][f"{HOME}#2"]["graphql_body"] = fm(
            f"{HOME}#2", blocked_by=[f"{HOME}#1", f"{ECHO}#6"]
        )
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(self.node(r, f"{HOME}#2")["open_parents"], [f"{ECHO}#6", f"{HOME}#1"])

    def test_missing_cursor_with_another_page_exits_2(self):
        state = plan_state()
        state["edits_page_size"] = 1
        state["graphql_no_cursor"] = True
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", STRANGER]
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        self.assertEqual(p.returncode, 2, p.stdout)

    def test_trust_owner_widens_the_scope(self):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = fm(f"{HOME}#1", blocked_by=["partner/lib#1"])
        state["issues"]["partner/lib#1"] = issue(
            4242,
            "Partner lib",
            fm("partner/lib#1"),
            options={"author": "pat", "association": "OWNER"},
        )
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9", "--trust-owner", "partner")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertIn("partner/lib#1", self.ids(r))

    def test_untrusted_root_is_listed_not_a_node(self):
        state = plan_state()
        state["issues"][f"{HOME}#77"] = issue(
            177, "Stranger", fm(f"{HOME}#77"), options={"author": STRANGER, "association": "NONE"}
        )
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#77")
        r = self.out(p)
        self.assertEqual(p.returncode, 0, r)
        self.assertEqual(self.ids(r), [])
        self.assertEqual(self.untrusted_ids(r), [f"{HOME}#77"])

    def test_root_outside_the_scope_is_refused(self):
        p = self.run_dag(plan_state(), "--from-github", "--root", "mallory/trap#1")
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertNotIn(["api", "repos/mallory/trap/issues/1"], self.calls())

    def test_untrusted_descendants_do_not_inflate_ranking(self):
        base = self.out(self.run_dag(plan_state(), "--from-github"))
        state = plan_state()
        for n in range(50, 60):
            state["issues"][f"{HOME}#{n}"] = issue(
                1000 + n,
                "Fake dependent",
                fm(f"{HOME}#{n}", blocked_by=[f"{HOME}#2"]),
                options={"author": STRANGER, "association": "NONE"},
            )
        r = self.out(self.run_dag(state, "--from-github"))
        self.assertEqual(
            self.node(r, f"{HOME}#2")["priority_score"],
            self.node(base, f"{HOME}#2")["priority_score"],
        )

    def test_trust_lookup_failure_fails_closed(self):
        state = plan_state()
        state["fail_graphql"] = True
        p = self.run_dag(state, "--from-github")
        self.assertEqual(p.returncode, 2, p.stdout)

    def test_edit_history_is_paginated(self):
        state = plan_state()
        state["edits_page_size"] = 2
        state["issues"][f"{HOME}#1"]["editors"] = ["owner", "owner", "owner", STRANGER]
        r = self.out(self.run_dag(state, "--from-github", "--root", f"{HOME}#9"))
        self.assertIn(f"{HOME}#1", self.untrusted_ids(r))

    def test_trust_flags_require_from_github(self):
        p = self.run_dag(plan_state(), "--trust", STRANGER)
        self.assertNotEqual(p.returncode, 0)
