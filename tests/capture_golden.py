#!/usr/bin/env python3
"""Capture the 1.x compiler's output for every scenario in golden_scenarios.py.

Not a test (unittest discovery skips it). Run it once against the compiler at the commit the
fixtures name, for example:

    git show 6e84058:skills/taskalisk/scripts/taskalisk.py > /some/scratch/taskalisk_v1.py
    python3 tests/capture_golden.py /some/scratch/taskalisk_v1.py 6e840586ab1b46f0e9f0039d56d248f991c89caf

Each fixture records the commit, the arguments, the exit status and the parsed stdout document (or, for a rendering, its text),
with the per-run temporary directory replaced by a placeholder. The fixtures are captured output,
never hand-written.
"""
import json
import os
import sys
import tempfile

import golden_scenarios as g


def main(script, commit):
    if not os.path.isfile(script):
        sys.exit(f"capture_golden: no such compiler script: {script}")
    g.GOLDEN.mkdir(parents=True, exist_ok=True)
    for name, (_, args, _) in g.SCENARIOS.items():
        with tempfile.TemporaryDirectory(prefix="taskalisk-golden-") as tmp:
            g.prepare(tmp)
            p = g.run_scenario(script, name, tmp)
            if not p.stdout.strip():  # a compiler that printed nothing is a failure, never a rendering
                sys.exit(f"capture_golden: {name}: the compiler printed nothing (exit {p.returncode}): {p.stderr[-300:]}")
            try:
                out = {"stdout": g.normalise(json.loads(p.stdout), tmp)}
            except json.JSONDecodeError:
                out = {"stdout_text": p.stdout}  # --emit-roadmap and --emit-mermaid printed text
        fixture = {"captured_from": f"flyingrobots/taskalisk@{commit} skills/taskalisk/scripts/taskalisk.py",
                   "scenario": name, "args": args, "exit": p.returncode, **out}
        (g.GOLDEN / f"{name}.json").write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"event": "captured", "scenario": name, "exit": p.returncode}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
