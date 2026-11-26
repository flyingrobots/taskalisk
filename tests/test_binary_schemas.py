"""The Parley schemas the Rust binary's `--help` names are the vendored writer's, byte for byte.

`crates/taskalisk/schemas/` holds copies of the two writer schemas a `plan --help` describes
(`parley.error` and `parley.startup.failed`), because the binary cannot read them from the Python
writer. This fails when a copy differs from the text `parley_emit.py` embeds.
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "taskalisk" / "scripts"))

import parley_emit as pe  # noqa: E402

COPIES = ROOT / "crates" / "taskalisk" / "schemas"


class BinaryOnlySchemas(unittest.TestCase):
    """Decision D22: `skills/taskalisk/schemas/binary/` holds the schemas only the Rust binary writes.

    Every schema there is one the binary embeds (`include_str!` from `crates/taskalisk/src/`), and
    no Python command lists it under `--schema`; it folds into the top level at the cutover (#32).
    """

    def test_every_binary_schema_is_written_by_the_binary_and_listed_by_no_python_command(self):
        binary = ROOT / "skills" / "taskalisk" / "schemas" / "binary"
        files = sorted(p.name for p in binary.glob("*.schema.json"))
        self.assertTrue(files, "no binary-only schema")
        sources = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "crates" / "taskalisk" / "src").glob("*.rs"))
        embedded = set(re.findall(r'include_str!\("[./]*skills/taskalisk/schemas/binary/([^"]+)"\)', sources))
        self.assertEqual(set(files), embedded, "a binary-only schema the binary does not embed, or the reverse")
        with tempfile.TemporaryDirectory() as cwd:
            p = subprocess.run([sys.executable, str(ROOT / "skills" / "taskalisk" / "scripts" / "taskalisk.py"), "--schema"],
                               cwd=cwd, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        listed = {json.loads(line).get("id") for line in p.stdout.splitlines() if '"parley.schema"' in line}
        for name in files:
            doc = json.loads((binary / name).read_text(encoding="utf-8"))
            schema_id = doc["properties"]["_schema"]["properties"]["id"]["const"]
            self.assertEqual(name, f"{schema_id}.schema.json")
            self.assertNotIn(schema_id, listed, f"{schema_id} is listed by a Python command")


class BinarySchemas(unittest.TestCase):
    def test_each_copy_is_the_writers_text(self):
        names = sorted(p.name for p in COPIES.glob("*.schema.json"))
        self.assertEqual(names, ["parley.error.schema.json", "parley.startup.failed.schema.json"])
        for name in names:
            self.assertEqual((COPIES / name).read_text(encoding="utf-8"), pe._SCHEMA_TEXT[name], name)


if __name__ == "__main__":
    unittest.main()
