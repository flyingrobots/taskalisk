"""Observe worktree inventory against owned repositories and real Git state."""

from __future__ import annotations

import shutil
from pathlib import Path

from cli_fixture import Harness

from skills.taskalisk.scripts.taskalisk_core.inventory import collect_worktrees
from skills.taskalisk.scripts.taskalisk_core.inventory_values import Worktree
from skills.taskalisk.scripts.taskalisk_core.process import run_cmd_checked


class WorktreeInventory(Harness):
    """Filesystem and Git observations must survive worktree record boundaries."""

    def setUp(self) -> None:
        """Create one committed baseline with a local origin/main observation."""
        super().setUp()
        self.tmp = self.tmp.resolve()
        self.repo = self.repo.resolve()
        self.git_command(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "baseline",
        )
        self.git_command("update-ref", "refs/remotes/origin/main", "HEAD")

    def git_command(self, *args: str, cwd: Path | None = None) -> str:
        """Run real Git in an owned fixture and fail before using a missing observation."""
        ok, output, error = run_cmd_checked(["git", *args], cwd=str(cwd or self.repo))
        self.assertTrue(ok, error)
        return output

    def observe(self, path: Path) -> tuple[Worktree, list[dict[str, str]]]:
        """Require one record for the actual fixture path without inventing missing fields."""
        errors: list[dict[str, str]] = []
        worktrees = collect_worktrees(str(self.repo), errors)
        matches = [worktree for worktree in worktrees if worktree.get("path") == str(path)]
        self.assertEqual(len(matches), 1, worktrees)
        return matches[0], errors

    def test_dirty_branch_records_its_real_head_and_divergence(self) -> None:
        """A separate checkout exposes its own untracked file, commit and branch."""
        path = self.tmp / "active"
        self.git_command("worktree", "add", "-b", "task/2-active", str(path))
        self.git_command(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "work",
            cwd=path,
        )
        (path / "untracked.txt").write_text("owned fixture\n")
        head = self.git_command("rev-parse", "--short=9", "HEAD", cwd=path)
        worktree, errors = self.observe(path)
        self.assertEqual(errors, [])
        self.assertEqual(
            worktree,
            {
                "path": str(path),
                "path_exists": True,
                "dirty": True,
                "ahead_of_main": 1,
                "behind_main": 0,
                "head": head,
                "branch": "task/2-active",
            },
        )

    def test_detached_locked_checkout_keeps_both_observations(self) -> None:
        """A lock line must not replace or lose the detached checkout's branch state."""
        path = self.tmp / "detached"
        self.git_command("worktree", "add", "--detach", str(path), "HEAD")
        self.git_command("worktree", "lock", "--reason", "owned fixture", str(path))
        worktree, errors = self.observe(path)
        self.assertEqual(errors, [])
        self.assertEqual(worktree.get("branch"), "(detached HEAD)")
        self.assertIs(worktree.get("locked"), expr2=True)
        self.assertIs(worktree.get("dirty"), expr2=False)

    def test_missing_checkout_is_prunable_without_a_status_error(self) -> None:
        """A registered missing directory remains visible without running Git inside it."""
        path = self.tmp / "missing"
        self.git_command("worktree", "add", "-b", "task/3-missing", str(path))
        shutil.rmtree(path)
        worktree, errors = self.observe(path)
        self.assertEqual(errors, [])
        self.assertIs(worktree.get("path_exists"), expr2=False)
        self.assertIn("dirty", worktree)
        self.assertIsNone(worktree.get("dirty"))
        self.assertIs(worktree.get("prunable"), expr2=True)
        self.assertEqual(worktree.get("branch"), "task/3-missing")

    def test_existing_directory_with_broken_git_metadata_reports_unknown_dirtiness(self) -> None:
        """A failed status command is an inventory error, not a clean working tree."""
        path = self.tmp / "broken"
        self.git_command("worktree", "add", "-b", "task/4-broken", str(path))
        (path / ".git").unlink()
        worktree, errors = self.observe(path)
        self.assertEqual([error["source"] for error in errors], [f"git status ({path})"])
        self.assertIs(worktree.get("path_exists"), expr2=True)
        self.assertIn("dirty", worktree)
        self.assertIsNone(worktree.get("dirty"))
        self.assertNotIn("ahead_of_main", worktree)
