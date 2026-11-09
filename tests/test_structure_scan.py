"""Check complete source inventory admission and the real structure-checker protocol."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.check_structure import scan_sources
from tools.source_inventory import (
    MAX_SOURCE_BYTES,
    MAX_SOURCE_DIRECTORIES,
    MAX_SOURCE_FILES,
    SOURCE_ROOTS,
    SourceDirectoryError,
    directory_sources,
    read_source,
)


class StructureScan(unittest.TestCase):
    """No incomplete or malformed source inventory may become a passing gate."""

    def setUp(self) -> None:
        """Create all required roots and one minimal valid source in an owned directory."""
        temporary = tempfile.TemporaryDirectory(prefix="taskalisk-structure-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in SOURCE_ROOTS:
            (self.root / name).mkdir(parents=True)
        self.source = self.root / "tools/example.py"
        self.source.write_text("pass\n", encoding="utf-8")
        (self.root / "tools/notes.txt").write_text("Not Python source.\n", encoding="utf-8")

    def test_valid_source_is_measured_and_bound_to_exact_bytes(self) -> None:
        """A passing report retains file identity and meaningful function measurements."""
        content = "def work(value):\r\n    return value\r\n"
        self.source.write_text(content, encoding="utf-8")
        result = scan_sources(self.root)
        self.assertTrue(result["ok"], result)
        self.assertEqual(
            result["sources"],
            [
                {
                    "path": "tools/example.py",
                    "sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "lines": 2,
                    "functions": [
                        {
                            "name": "work",
                            "line": 1,
                            "logical_lines": 1,
                            "nesting": 0,
                            "parameters": 1,
                            "tuple_arity": 0,
                        }
                    ],
                }
            ],
        )

    def test_invalid_source_refuses_the_whole_scan_without_dropping_valid_evidence(self) -> None:
        """One valid file cannot hide a later syntax failure."""
        (self.root / "tests/broken.py").write_text("def (", encoding="utf-8")
        result = scan_sources(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"], ["tests/broken.py: cannot measure source (SyntaxError)"])
        self.assertEqual([entry["path"] for entry in result["sources"]], ["tools/example.py"])

    def test_handwritten_stubs_are_included_in_source_limits(self) -> None:
        """A stub cannot hide an oversized public function signature from the source gate."""
        (self.root / "tools/api.pyi").write_text(
            "def work(a, b, c, d, e, f): ...\n", encoding="utf-8"
        )
        result = scan_sources(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(
            [(entry["path"], entry["rule"]) for entry in result["findings"]],
            [("tools/api.pyi", "PY-FUNCTION-PARAMETERS")],
        )

    def test_missing_root_and_empty_inventory_fail(self) -> None:
        """Deleting a maintained scope or all source cannot turn the checker green."""
        (self.root / "tests").rmdir()
        result = scan_sources(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("tests: missing or linked source directory", result["errors"])
        self.source.unlink()
        self.assertIn("no maintained Python sources", scan_sources(self.root)["errors"])

    def test_invalid_utf8_and_oversized_sources_are_refused(self) -> None:
        """The reader does not allocate an unbounded file or replace malformed text."""
        for payload, error in (
            (b"\xff", "UnicodeDecodeError"),
            (b" " * (MAX_SOURCE_BYTES + 1), "SourceSizeError"),
        ):
            with self.subTest(error=error):
                self.source.write_bytes(payload)
                result = scan_sources(self.root)
                self.assertFalse(result["ok"])
                self.assertEqual(
                    result["errors"], [f"tools/example.py: cannot measure source ({error})"]
                )

    def test_exact_byte_limit_is_read_without_truncation(self) -> None:
        """The valid inclusive byte boundary remains readable."""
        payload = "#" + "x" * (MAX_SOURCE_BYTES - 1)
        self.source.write_text(payload, encoding="utf-8")
        self.assertEqual(read_source(self.source), payload)

    def test_fifo_and_symlink_sources_are_refused_without_following_them(self) -> None:
        """Source admission checks the opened file kind before reading content."""
        self.source.unlink()
        os.mkfifo(self.source)
        result = scan_sources(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(
            result["errors"], ["tools/example.py: cannot measure source (SourceKindError)"]
        )
        self.source.unlink()
        self.source.symlink_to(self.root / "unread-target.py")
        result = scan_sources(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"], ["tools/example.py: cannot measure source (OSError)"])

    def test_linked_subtree_cannot_silently_hide_sources(self) -> None:
        """A linked source directory is a refusal instead of an unexamined subtree."""
        target = self.root / "external"
        target.mkdir()
        (target / "hidden.py").write_text("def work(a, b, c, d, e, f): pass\n", encoding="utf-8")
        (self.root / "tools/linked").symlink_to(target, target_is_directory=True)
        result = scan_sources(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("tools: cannot enumerate sources", result["errors"])

    def test_real_enumeration_errors_are_not_silently_ignored(self) -> None:
        """Trying to enumerate a regular file exposes the actual filesystem failure."""
        with self.assertRaises(NotADirectoryError):
            list(directory_sources(self.source))

    def test_directory_traversal_has_a_finite_inclusive_ceiling(self) -> None:
        """Empty directories cannot evade resource bounds merely by containing no Python files."""
        parent = self.root / "tools"
        for index in range(MAX_SOURCE_DIRECTORIES - 1):
            (parent / f"empty_{index}").mkdir()
        self.assertEqual(list(directory_sources(parent)), [self.source])
        (parent / "one_too_many").mkdir()
        with self.assertRaises(SourceDirectoryError):
            list(directory_sources(parent))

    def test_oversized_inventory_is_refused_before_measurement(self) -> None:
        """The file-count ceiling cannot silently admit a prefix of a larger source tree."""
        for index in range(MAX_SOURCE_FILES):
            (self.root / "tests" / f"sample_{index}.py").write_text("pass\n", encoding="utf-8")
        result = scan_sources(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"], ["maintained source inventory exceeds 1000 files"])
        self.assertEqual(result["sources"], [])

    def test_cli_emits_json_and_exit_status_for_both_control_and_violation(self) -> None:
        """The executable gate distinguishes a valid fixture from a concrete tuple violation."""
        for source, expected in (("pass\n", 0), ("def work(): return 1, 2, 3, 4\n", 1)):
            self.source.write_text(source, encoding="utf-8")
            # policy-exception: PY-STRUCTURE-ARGV -- Fixed module and owned fixture root.
            result = subprocess.run(  # noqa: S603
                [sys.executable, "-m", "tools.check_structure", "--root", str(self.root)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            with self.subTest(expected=expected):
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(json.loads(result.stdout)["ok"], expected == 0)
                self.assertEqual(result.stderr, "")
