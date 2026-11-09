"""Exercise regular-file and decoder budgets without allocating large fixtures."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skills.taskalisk.scripts.taskalisk_core.github_json_limits import JsonLimits
from skills.taskalisk.scripts.taskalisk_core.spec_file import read_spec


class SpecFile(unittest.TestCase):
    """The local file adapter must enforce tightened limits before graph admission."""

    def test_exact_byte_ceiling_accepts_and_one_less_refuses(self) -> None:
        """The file budget counts bytes, including multibyte text, rather than characters."""
        raw = '{"extra":"é"}'.encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spec.json"
            path.write_bytes(raw)
            with self.subTest(check="exact"):
                self.assertEqual(
                    read_spec(str(path), limits=JsonLimits(max_bytes=len(raw))),
                    {"merged": set(), "nodes": {}},
                )
            with self.subTest(check="exceeded"), self.assertRaisesRegex(ValueError, "exceeds"):
                read_spec(str(path), limits=JsonLimits(max_bytes=len(raw) - 1))

    def test_depth_and_token_budgets_are_forwarded(self) -> None:
        """A small file cannot evade structural limits using nested or dense JSON."""
        cases = (
            (b'{"nodes":{}}', JsonLimits(max_depth=1), "depth"),
            (b'{"nodes":{}}', JsonLimits(max_tokens=1), "tokens"),
            (b"", JsonLimits(), "empty response"),
            (b"null", JsonLimits(), "DAG spec must be an object"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "spec.json"
            for raw, limits, diagnostic in cases:
                path.write_bytes(raw)
                with (
                    self.subTest(diagnostic=diagnostic),
                    self.assertRaisesRegex((TypeError, ValueError), diagnostic),
                ):
                    read_spec(str(path), limits=limits)

    def test_nonregular_and_absent_paths_are_not_empty_specs(self) -> None:
        """Unsupported or absent paths fail before creating a plan."""
        with tempfile.TemporaryDirectory() as directory:
            with self.subTest(kind="directory"), self.assertRaisesRegex(ValueError, "regular file"):
                read_spec(directory)
            with self.subTest(kind="absent"), self.assertRaises(FileNotFoundError):
                read_spec(str(Path(directory) / "missing"))
