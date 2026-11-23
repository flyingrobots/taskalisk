#!/usr/bin/env python3
"""Capture real runs of the compiler for the Parley doctor (OUT-19).

Not a test (unittest discovery skips it). Each run uses the offline fake `gh`, in a fresh
directory under BASE, and its stdout, stderr and receipt are copied byte for byte to
tests/fixtures/doctor/<name>/, with meta.json recording the arguments and the exit status.

    python3 tests/capture_doctor_runs.py /tmp/taskalisk-doctor-capture

Then, from a flyingrobots/parley checkout, run the doctor on each (docs/topics/output/README.md
records the runs and their verdicts):

    bun run doctor --stdout <run>/stdout.jsonl --stderr <run>/stderr.jsonl --receipt <run>/receipt.jsonl
    bun run doctor --receipt human/receipt.jsonl

The suite re-validates every committed line offline (tests/test_parley_output.py, DoctorFixtures).
"""
import json
import os
import pathlib
import shutil
import sys

import golden_scenarios as g

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "skills" / "taskalisk" / "scripts" / "taskalisk.py"
OUT = HERE / "fixtures" / "doctor"

# name -> (golden scenario, extra arguments)
RUNS = {
    "plan": ("plan_rich", []),
    "inventory": ("inventory_ok", []),
    "edit": ("edit_add", []),
    "edit-cycle": ("edit_cycle", []),
    "gh-failure": ("plan_gh_failure", []),
    "verify": ("verify_ok", []),
    "help": ("plan_home", ["--help"]),
    "schema": ("plan_home", ["--schema"]),
    "human": ("plan_rich", ["--human"]),
}


def main(base):
    base = pathlib.Path(base)
    base.mkdir(parents=True, exist_ok=True)
    for name, (scenario, extra) in RUNS.items():
        tmp = base / name
        tmp.mkdir()  # a fresh directory per capture; an existing one is an error, never reused
        g.prepare(tmp)
        for k in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "PARLEY_SESSION"):
            os.environ.pop(k, None)  # a captured run carries no credential of the machine that captured it
        p = g.run_scenario(SCRIPT, scenario, tmp, extra_args=extra, env_extra={"XDG_STATE_HOME": str(tmp / "state")})
        receipts = sorted((tmp / ".parley" / "receipts").glob("*.jsonl"))
        dest = OUT / name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "stdout.jsonl").write_text(p.stdout)
        (dest / "stderr.jsonl").write_text(p.stderr)
        if receipts:
            shutil.copyfile(receipts[-1], dest / "receipt.jsonl")
        args = [a.replace(str(tmp), "<capture dir>") for a in g.SCENARIOS[scenario][1] + extra]
        (dest / "meta.json").write_text(json.dumps({"scenario": scenario, "args": args, "exit": p.returncode,
                                                    "captured": "a real run of skills/taskalisk/scripts/taskalisk.py against tests/fake_gh.py"}, indent=2) + "\n")
        print(json.dumps({"event": "captured", "run": name, "exit": p.returncode, "receipt": bool(receipts)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
