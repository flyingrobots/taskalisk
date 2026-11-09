"""Check Parsing behavior through the public CLI."""

import json
import subprocess
import sys

from cli_fixture import HOME, SCRIPT, Harness
from fake_values import field


class Parsing(Harness):
    """Preserve read-only planning from a hand-written DAG specification."""

    def test_verify_dag_spec_still_works(self) -> None:
        """The hand-written two-node spec retains its critical path."""
        spec = self.tmp / "dag.json"
        spec.write_text(
            json.dumps(
                {
                    "nodes": {
                        f"{HOME}#1": {"title": "a"},
                        f"{HOME}#2": {"title": "b", "depends_on": [f"{HOME}#1"]},
                    }
                }
            )
        )
        p = subprocess.run(
            [sys.executable, str(SCRIPT), "--verify-dag", str(spec)], capture_output=True, text=True
        )
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(field(self.out(p), "metrics", "critical_path"), [f"{HOME}#1", f"{HOME}#2"])
