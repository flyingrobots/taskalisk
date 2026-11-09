"""Check QualifiedReferences behavior through the public CLI."""

from cli_fixture import BUNNY, ECHO, HOME, Harness, fm, plan_state


class QualifiedReferences(Harness):
    def run_with(self, body_for_1):
        state = plan_state()
        state["issues"][f"{HOME}#1"]["body"] = body_for_1
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        return p, self.out(p)

    def test_bare_blocker_number_is_invalid(self):
        p, r = self.run_with(fm(f"{HOME}#1", blocked_by=["#2"]))
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(
            any(
                "bare numbers are not allowed" in v
                for v in r["frontmatter"]["violations"][f"{HOME}#1"]
            )
        )

    def test_bare_id_is_invalid(self):
        p, r = self.run_with(fm("#1", blocked_by=[f"{ECHO}#5"]))
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(
            any("must be owner/repo#N" in v for v in r["frontmatter"]["violations"][f"{HOME}#1"])
        )

    def test_retired_schema_is_invalid(self):
        p, r = self.run_with(
            fm(f"{HOME}#1", blocked_by=[f"{ECHO}#5"]).replace("issue-dag/2", "issue-dag/1")
        )
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(any("retired" in v for v in r["frontmatter"]["violations"][f"{HOME}#1"]))

    def test_bare_cli_references_are_rejected(self):
        for args in (["--add-edge", f"#5->{HOME}#2"], ["--root", "#9"]):
            p = self.run_dag(plan_state(), "--from-github", *args)
            self.assertNotEqual(p.returncode, 0, args)

    def test_transferred_reference_is_reported(self):
        state = plan_state()
        state["moved"] = {f"{ECHO}#6": f"{BUNNY}#66"}
        state["issues"][f"{BUNNY}#66"] = state["issues"].pop(f"{ECHO}#6")
        p = self.run_dag(state, "--from-github", "--root", f"{HOME}#9")
        r = self.out(p)
        self.assertEqual(p.returncode, 1, r)
        self.assertTrue(
            any(
                f"{ECHO}#6 moved to {BUNNY}#66" in v
                for v in r["frontmatter"]["violations"][f"{HOME}#9"]
            )
        )

    def test_output_ids_are_always_qualified(self):
        r = self.out(self.run_dag(plan_state(), "--from-github", "--root", f"{HOME}#9"))
        self.assertTrue(all("/" in i.split("#")[0] for i in self.ids(r)))
