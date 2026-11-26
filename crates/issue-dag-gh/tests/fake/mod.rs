//! A fake `gh` on `PATH`: the repository's `tests/fake_gh.py`, which answers
//! from a JSON state and logs every argument vector it is given.

use std::ffi::OsString;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};

use issue_dag_core::Repo;
use issue_dag_gh::GhForge;
use serde_json::Value;

static NEXT: AtomicUsize = AtomicUsize::new(0);

/// A directory holding a `gh` that runs the fake, its state and its log.
pub struct Fake {
    dir: PathBuf,
}

impl Fake {
    /// A fake answering from `state`.
    pub fn new(state: &Value) -> Self {
        let dir = std::env::temp_dir().join(format!(
            "issue-dag-gh-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir_all(dir.join("bin")).expect("a temporary directory");
        let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fake_gh.py");
        let script = script.canonicalize().expect("tests/fake_gh.py");
        let gh = dir.join("bin/gh");
        fs::write(
            &gh,
            format!("#!/bin/sh\nexec python3 '{}' \"$@\"\n", script.display()),
        )
        .expect("the gh wrapper");
        fs::set_permissions(&gh, fs::Permissions::from_mode(0o755)).expect("an executable gh");
        fs::write(dir.join("state.json"), state.to_string()).expect("the state");
        fs::write(dir.join("log"), "").expect("the log");
        Self { dir }
    }

    /// A forge for `home` that finds this fake as `gh` on `PATH`.
    pub fn forge(&self, home: &str) -> GhForge {
        let mut path = OsString::from(self.dir.join("bin"));
        if let Some(rest) = std::env::var_os("PATH") {
            path.push(":");
            path.push(rest);
        }
        GhForge::new(Repo::parse(home).expect("a repository"))
            .env("PATH", path)
            .env("FAKE_GH_STATE", self.dir.join("state.json"))
            .env("FAKE_GH_LOG", self.dir.join("log"))
    }

    /// Every argument vector the fake was run with, in order.
    pub fn calls(&self) -> Vec<Vec<String>> {
        fs::read_to_string(self.dir.join("log"))
            .expect("the log")
            .lines()
            .map(|line| serde_json::from_str(line).expect("a logged argument vector"))
            .collect()
    }
}

// Each test binary that includes this module uses only some of these.
#[allow(dead_code)]
impl Fake {
    /// The fake's state now, as its writes left it.
    pub fn state(&self) -> Value {
        serde_json::from_str(&fs::read_to_string(self.dir.join("state.json")).expect("the state"))
            .expect("a JSON state")
    }

    /// For each run, the variables the state's `record_env` names, as `gh`
    /// saw them (`null` when unset).
    pub fn environments(&self) -> Vec<Value> {
        fs::read_to_string(self.dir.join("log.env"))
            .unwrap_or_default()
            .lines()
            .map(|line| serde_json::from_str(line).expect("a logged environment"))
            .collect()
    }
}

impl Drop for Fake {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
    }
}
