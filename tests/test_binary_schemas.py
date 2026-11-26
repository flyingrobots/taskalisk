"""The Parley schemas the Rust binary's `--help` names are the vendored writer's, byte for byte.

`crates/taskalisk/schemas/` holds copies of the two writer schemas a `plan --help` describes
(`parley.error` and `parley.startup.failed`), because the binary cannot read them from the Python
writer. This fails when a copy differs from the text `parley_emit.py` embeds.
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "taskalisk" / "scripts"))

import parley_emit as pe  # noqa: E402

COPIES = ROOT / "crates" / "taskalisk" / "schemas"


class BinarySchemas(unittest.TestCase):
    def test_each_copy_is_the_writers_text(self):
        names = sorted(p.name for p in COPIES.glob("*.schema.json"))
        self.assertEqual(names, ["parley.error.schema.json", "parley.startup.failed.schema.json"])
        for name in names:
            self.assertEqual((COPIES / name).read_text(encoding="utf-8"), pe._SCHEMA_TEXT[name], name)


if __name__ == "__main__":
    unittest.main()
