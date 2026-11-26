//! The binary against GitHub itself, read-only. Ignored by default because
//! it needs the network and an authenticated `gh`; run it on a checkout of
//! a repository whose issues carry `issue-dag/2` frontmatter:
//!
//! ```sh
//! TASKALISK_LIVE_CHECKOUT=~/git/taskalisk \
//!   cargo test -p taskalisk --test live -- --ignored
//! ```
//!
//! It checks the acceptance of flyingrobots/taskalisk#31: the plan matches
//! the Python's on the same backlog, and no issue the maintainers wrote is
//! untrusted. Both write their receipts to a temporary directory.
#![cfg(unix)]

use std::path::PathBuf;
use std::process::Command;

use serde_json::Value;

fn checkout() -> PathBuf {
    PathBuf::from(
        std::env::var_os("TASKALISK_LIVE_CHECKOUT")
            .expect("set TASKALISK_LIVE_CHECKOUT to a checkout"),
    )
}

/// The plan line and the findings of a run's stdout.
fn plan_of(program: &mut Command) -> (i32, Value, Vec<Value>) {
    let dir = std::env::temp_dir().join(format!("taskalisk-live-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("a temporary directory");
    let out = program.current_dir(&dir).output().expect("it runs");
    let lines: Vec<Value> = String::from_utf8_lossy(&out.stdout)
        .lines()
        .map(|l| serde_json::from_str(l).expect("JSON"))
        .collect();
    let id = |l: &Value| l["_schema"]["id"].as_str().unwrap_or_default().to_owned();
    let plan = lines
        .iter()
        .find(|l| id(l) == "taskalisk.plan")
        .cloned()
        .unwrap_or_else(|| panic!("no plan: {}", String::from_utf8_lossy(&out.stderr)));
    let findings = lines
        .into_iter()
        .filter(|l| id(l) == "taskalisk.finding")
        .collect();
    (out.status.code().unwrap_or(-1), plan, findings)
}

#[test]
#[ignore = "needs the network and an authenticated gh"]
fn a_live_backlog_plans_as_the_python_plans_it() {
    let repo = checkout();
    let (status, rust, findings) = plan_of(
        Command::new(env!("CARGO_BIN_EXE_taskalisk"))
            .args(["plan", "--repo"])
            .arg(&repo),
    );
    assert_eq!(status, 0, "{rust}");
    assert_eq!(rust["ok"], true, "{rust}");
    let untrusted: Vec<&Value> = findings
        .iter()
        .filter(|f| f["code"] == "issue.untrusted")
        .map(|f| &f["subject"])
        .collect();
    assert_eq!(untrusted, Vec::<&Value>::new(), "untrusted issues");

    let script = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../skills/taskalisk/scripts/taskalisk.py");
    let (_, python, _) = plan_of(
        Command::new("python3")
            .arg(script)
            .args(["plan", "--repo"])
            .arg(&repo),
    );
    for key in [
        "outcome",
        "frontier",
        "batch",
        "metrics",
        "open_frontier_count",
    ] {
        assert_eq!(rust[key], python[key], "{key}");
    }
}
