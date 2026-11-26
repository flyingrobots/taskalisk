//! The `taskalisk` binary's `edit` against the fake `gh` (`tests/fake_gh.py`,
//! found as `gh` on `PATH`): the edge edit of flyingrobots/taskalisk#1. It
//! checks the edit before any write, rereads the child immediately before
//! the one `PATCH`, never restores a body and never retries. No test here
//! writes to GitHub.
#![cfg(unix)]

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};

use serde_json::{Value, json};

static NEXT: AtomicUsize = AtomicUsize::new(0);

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("the repository root")
}

/// A task document of `id` waiting on `blocked_by`.
fn task(id: &str, blocked_by: &[&str]) -> String {
    format!(
        "```yaml\n.dag: issue-dag/2\n.id: {id}\n.kind: task\n.type: feature\n.blocked_by: [{}]\n```\n\n## Outcome\n\nText.\n",
        blocked_by.join(", ")
    )
}

fn issue(id: u64, body: &str) -> Value {
    json!({"id": id, "title": format!("Issue {id}"), "state": "open", "labels": [], "body": body,
           "author": "owner", "association": "OWNER"})
}

/// `o/r`: 1 <- 2 <- 3 (2 waits on 1, 3 on 2), and 5 alone. The owner and
/// `dev` can write.
fn chain() -> Value {
    json!({
        "home": "o/r",
        "blocked_by": {},
        "collaborators": {"o/r": ["owner", "dev"]},
        "issues": {
            "o/r#1": issue(1, &task("o/r#1", &[])),
            "o/r#2": issue(2, &task("o/r#2", &["o/r#1"])),
            "o/r#3": issue(3, &task("o/r#3", &["o/r#2"])),
            "o/r#5": issue(5, &task("o/r#5", &[])),
        }
    })
}

struct Fixture {
    dir: PathBuf,
}

impl Fixture {
    fn new(state: &Value) -> Self {
        let dir = std::env::temp_dir().join(format!(
            "taskalisk-edit-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("bin")).expect("a temporary directory");
        let dir = dir.canonicalize().expect("a canonical directory");
        let gh = dir.join("bin/gh");
        fs::write(
            &gh,
            format!(
                "#!/bin/sh\nexec python3 '{}' \"$@\"\n",
                root().join("tests/fake_gh.py").display()
            ),
        )
        .expect("the gh wrapper");
        fs::set_permissions(&gh, fs::Permissions::from_mode(0o755)).expect("an executable gh");
        fs::write(dir.join("state.json"), state.to_string()).expect("the state");
        fs::write(dir.join("log"), "").expect("the log");
        let repo = dir.join("repo");
        fs::create_dir_all(&repo).expect("the repository");
        for args in [
            &["init", "-q", "-b", "main"][..],
            &[
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "base",
            ],
        ] {
            let status = Command::new("git")
                .args(args)
                .current_dir(&repo)
                .env("GIT_AUTHOR_NAME", "Fixture")
                .env("GIT_AUTHOR_EMAIL", "fixture@example.invalid")
                .env("GIT_COMMITTER_NAME", "Fixture")
                .env("GIT_COMMITTER_EMAIL", "fixture@example.invalid")
                .status()
                .expect("git runs");
            assert!(status.success(), "git {args:?}");
        }
        Self { dir }
    }

    /// The binary with `args` after `--repo <the fixture's repository>`.
    fn run(&self, args: &[&str]) -> Run {
        let cwd = self.dir.join("cwd");
        fs::create_dir_all(&cwd).expect("the working directory");
        let mut path = self.dir.join("bin").into_os_string();
        path.push(":");
        path.push(std::env::var_os("PATH").unwrap_or_default());
        let mut command = Command::new(env!("CARGO_BIN_EXE_taskalisk"));
        command
            .current_dir(&cwd)
            .env("PATH", path)
            .env("FAKE_GH_STATE", self.dir.join("state.json"))
            .env("FAKE_GH_LOG", self.dir.join("log"))
            .stdin(Stdio::null());
        for name in [
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "GH_ENTERPRISE_TOKEN",
            "GITHUB_ENTERPRISE_TOKEN",
        ] {
            command.env_remove(name);
        }
        let repo = self.dir.join("repo");
        let output = command
            .arg("edit")
            .arg("--repo")
            .arg(&repo)
            .args(args)
            .output()
            .expect("the binary runs");
        Run { output }
    }

    fn calls(&self) -> Vec<Vec<String>> {
        fs::read_to_string(self.dir.join("log"))
            .expect("the log")
            .lines()
            .map(|line| serde_json::from_str(line).expect("a logged argument vector"))
            .collect()
    }

    fn patches(&self) -> usize {
        self.calls()
            .iter()
            .filter(|argv| argv.iter().any(|a| a == "PATCH"))
            .count()
    }

    fn asked_for_the_writer(&self) -> bool {
        self.calls().iter().any(|argv| argv == &["api", "user"])
    }

    fn state(&self) -> Value {
        serde_json::from_str(&fs::read_to_string(self.dir.join("state.json")).expect("the state"))
            .expect("a JSON state")
    }

    fn body(&self, id: &str) -> String {
        self.state()["issues"][id]["body"]
            .as_str()
            .expect("a body")
            .to_owned()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
    }
}

struct Run {
    output: Output,
}

fn lines(bytes: &[u8]) -> Vec<Value> {
    String::from_utf8(bytes.to_vec())
        .expect("UTF-8")
        .lines()
        .map(|line| serde_json::from_str(line).expect("a JSON line"))
        .collect()
}

impl Run {
    fn status(&self) -> i32 {
        self.output.status.code().expect("an exit status")
    }

    fn stdout(&self) -> Vec<Value> {
        lines(&self.output.stdout)
    }

    fn errors(&self) -> Vec<Value> {
        lines(&self.output.stderr)
            .into_iter()
            .filter(|l| l["event"] == "error")
            .collect()
    }

    fn codes(&self) -> Vec<String> {
        self.errors()
            .iter()
            .map(|e| e["code"].as_str().unwrap_or_default().to_owned())
            .collect()
    }

    fn edge_edit(&self) -> Option<Value> {
        self.stdout()
            .into_iter()
            .find(|l| l["event"] == "edge_edit")
    }

    fn describe(&self) -> String {
        format!(
            "status {}\nstdout:\n{}\nstderr:\n{}",
            self.status(),
            String::from_utf8_lossy(&self.output.stdout),
            String::from_utf8_lossy(&self.output.stderr)
        )
    }
}

/// A refused edit: exit 2, the one error `code`, no write and no `edge_edit`.
fn assert_refused(fixture: &Fixture, run: &Run, code: &str) {
    assert_eq!(run.status(), 2, "{}", run.describe());
    assert_eq!(run.codes(), vec![code.to_owned()], "{}", run.describe());
    assert_eq!(fixture.patches(), 0, "nothing was written");
    assert!(run.edge_edit().is_none(), "{}", run.describe());
}

// Acceptance 1: a cycle-creating add-edge performs no PATCH, including when
// the changed child is outside explicit roots.

#[test]
fn an_added_edge_that_closes_a_cycle_is_refused_without_a_patch() {
    let fixture = Fixture::new(&chain());
    let before = fixture.body("o/r#1");
    let run = fixture.run(&["--add-edge", "o/r#3->o/r#1"]);
    assert_refused(&fixture, &run, "edge.cycle");
    let error = &run.errors()[0];
    assert_eq!(error["detail"]["child"], "o/r#1");
    assert!(
        error["detail"]["cyclic_nodes"]
            .as_array()
            .is_some_and(|n| n.contains(&json!("o/r#1"))),
        "{error}"
    );
    assert!(!fixture.asked_for_the_writer(), "checked before the writer");
    assert_eq!(fixture.body("o/r#1"), before);
}

#[test]
fn a_cycle_is_refused_when_the_roots_do_not_reach_the_child() {
    let fixture = Fixture::new(&chain());
    let run = fixture.run(&["--root", "o/r#5", "--add-edge", "o/r#3->o/r#1"]);
    assert_refused(&fixture, &run, "edge.cycle");
}

// Acceptance 2: an observed body change or newly untrusted editor before the
// write is refused without PATCH. The fake applies another person's edit just
// before the child's second edit-history read, the final reread.

#[test]
fn a_body_changed_before_the_final_reread_is_refused() {
    let mut state = chain();
    let theirs = task("o/r#5", &["o/r#2"]);
    state["edit_on_read"] = json!({"issue": "o/r#5", "read": 2, "body": theirs});
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#5"]);
    assert_refused(&fixture, &run, "edge.conflict");
    let error = &run.errors()[0];
    assert_eq!(error["detail"]["child"], "o/r#5");
    assert_eq!(error["detail"]["conflict"], "body");
    assert!(
        error["problem"]
            .as_str()
            .unwrap_or_default()
            .contains("o/r#5")
    );
    assert_eq!(fixture.body("o/r#5"), theirs, "their edit is kept");
}

#[test]
fn a_newly_untrusted_editor_before_the_final_reread_is_refused() {
    let mut state = chain();
    state["edit_on_read"] = json!({"issue": "o/r#5", "read": 2,
                                   "editors": ["owner", "mallory"]});
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#5"]);
    assert_refused(&fixture, &run, "edge.conflict");
    assert_eq!(run.errors()[0]["detail"]["conflict"], "trust");
}

// Acceptance 3: an unknown or untrusted writer is refused before PATCH;
// successful fake writes record their editor identity.

#[test]
fn an_untrusted_writer_is_refused_before_the_patch() {
    let mut state = chain();
    state["writer"] = json!({"login": "mallory", "type": "User"});
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#5"]);
    assert_refused(&fixture, &run, "edge.writer_untrusted");
    assert_eq!(run.errors()[0]["detail"]["writer"], "mallory");
}

#[test]
fn a_writer_that_cannot_be_identified_is_refused_before_the_patch() {
    let mut state = chain();
    state["writer_fail"] = json!(true);
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#5"]);
    assert_refused(&fixture, &run, "gh.command_failed");
    assert_eq!(run.errors()[0]["detail"]["phase"], "edge_edit");
}

#[test]
fn a_bot_writer_needs_an_explicit_allowlist_entry() {
    let mut state = chain();
    state["writer"] = json!({"login": "helper", "type": "Bot"});
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#5"]);
    assert_refused(&fixture, &run, "edge.writer_untrusted");
    let run = fixture.run(&["--trust", "helper[bot]", "--add-edge", "o/r#1->o/r#5"]);
    assert_eq!(run.status(), 0, "{}", run.describe());
    assert_eq!(fixture.patches(), 1);
}

#[test]
fn a_successful_write_patches_once_and_records_its_editor() {
    let mut state = chain();
    state["writer"] = json!({"login": "dev", "type": "User"});
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#5", "--reason", "1 first"]);
    assert_eq!(run.status(), 0, "{}", run.describe());
    assert_eq!(fixture.patches(), 1);
    assert_eq!(fixture.body("o/r#5"), task("o/r#5", &["o/r#1"]));
    let editors = fixture.state()["issues"]["o/r#5"]["editors"].clone();
    assert_eq!(
        editors.as_array().and_then(|e| e.last()),
        Some(&json!({"login": "dev", "type": "User"}))
    );
    let stdout = run.stdout();
    assert_eq!(
        stdout[1]["event"], "edge_edit",
        "first result after bootstrap"
    );
    let edit = &stdout[1];
    assert_eq!(edit["type"], "add_blocked_by");
    assert_eq!(edit["parent"], "o/r#1");
    assert_eq!(edit["child"], "o/r#5");
    assert_eq!(edit["changed"], true);
    assert_eq!(edit["reason"], "1 first");
    assert_eq!(edit["_schema"]["id"], "taskalisk.edge_edit");
    assert!(edit.get("rolled_back").is_none());
    // The plan follows, over the validated proposal: 5 now waits on 1.
    let plan = stdout
        .iter()
        .find(|l| l["event"] == "plan")
        .expect("a plan");
    assert_eq!(plan["ok"], true, "{plan}");
    assert!(
        !plan["frontier"]
            .as_array()
            .expect("a frontier")
            .contains(&json!("o/r#5"))
    );
    // The writer is read after the checks and before the reread and the write.
    let calls = fixture.calls();
    let at = |pred: &dyn Fn(&Vec<String>) -> bool| calls.iter().position(pred).expect("a call");
    let user = at(&|a| a == &["api", "user"]);
    let patch = at(&|a| a.iter().any(|x| x == "PATCH"));
    let last_read = calls
        .iter()
        .rposition(|a| {
            a.first().is_some_and(|x| x == "api") && a.get(1).is_some_and(|x| x == "graphql")
        })
        .expect("an edit-history read");
    assert!(user < last_read && last_read < patch, "{calls:?}");
}

// Acceptance 4: required lookup failures occur before writes; no rollback
// overwrites newer content.

#[test]
fn a_required_lookup_failure_is_reported_before_any_write() {
    let mut state = chain();
    state["fail_graphql_for"] = json!(["o/r#2"]);
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#3->o/r#5"]);
    assert_refused(&fixture, &run, "gh.command_failed");
    assert_eq!(run.errors()[0]["detail"]["phase"], "edge_edit");
}

#[test]
fn a_parent_that_resolves_to_nothing_is_reported_before_any_write() {
    let fixture = Fixture::new(&chain());
    let run = fixture.run(&["--add-edge", "o/r#99->o/r#5"]);
    // The incomplete outcome is reported as a plan reports it.
    assert_eq!(run.status(), 2, "{}", run.describe());
    assert_eq!(fixture.patches(), 0);
    assert!(run.edge_edit().is_none());
    let errors = run.errors();
    assert_eq!(errors.len(), 1, "{}", run.describe());
    assert!(
        errors[0]["problem"]
            .as_str()
            .unwrap_or_default()
            .contains("o/r#99"),
        "{}",
        run.describe()
    );
    assert_eq!(errors[0]["detail"]["phase"], "edge_edit");
}

#[test]
fn a_failed_patch_is_reported_once_and_never_restored() {
    let mut state = chain();
    state["patch_fail"] = json!(true);
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#5"]);
    assert_eq!(run.status(), 2, "{}", run.describe());
    assert_eq!(run.codes(), vec!["gh.mutation_failed".to_owned()]);
    let error = &run.errors()[0];
    assert_eq!(error["retryable"], false, "never retried blindly");
    assert_eq!(error["detail"]["write_outcome"], "unknown");
    assert_eq!(fixture.patches(), 1, "one PATCH, no retry");
}

#[test]
fn a_patch_whose_answer_is_lost_is_not_followed_by_a_restore() {
    let mut state = chain();
    state["patch_lost"] = json!(true);
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#5"]);
    assert_eq!(run.status(), 2, "{}", run.describe());
    assert_eq!(run.codes(), vec!["gh.mutation_failed".to_owned()]);
    assert_eq!(fixture.patches(), 1, "no restoring PATCH");
    assert_eq!(fixture.body("o/r#5"), task("o/r#5", &["o/r#1"]));
}

#[test]
fn an_edit_refused_by_a_rule_names_the_issue_and_writes_nothing() {
    let mut state = chain();
    state["issues"]["o/r#5"]["author"] = json!("mallory");
    state["issues"]["o/r#5"]["association"] = json!("NONE");
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#5"]);
    assert_refused(&fixture, &run, "edge.child_untrusted");
    let fixture = Fixture::new(&chain());
    let run = fixture.run(&["--add-edge", "x/y#1->o/r#5"]);
    assert_refused(&fixture, &run, "edge.out_of_scope");
    let mut state = chain();
    state["issues"]["o/r#5"]["body"] = json!("No frontmatter.");
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#5"]);
    assert_refused(&fixture, &run, "edge.child_frontmatter_missing");
}

// Acceptance 5: no-op edits do not PATCH; remove-edge can repair an
// out-of-scope reference.

#[test]
fn a_no_op_edit_does_not_patch_or_ask_for_the_writer() {
    let fixture = Fixture::new(&chain());
    let run = fixture.run(&["--add-edge", "o/r#1->o/r#2"]);
    assert_eq!(run.status(), 0, "{}", run.describe());
    assert_eq!(fixture.patches(), 0);
    assert!(!fixture.asked_for_the_writer());
    let edit = run.edge_edit().expect("an edge_edit line");
    assert_eq!(edit["changed"], false);
    let run = fixture.run(&["--remove-edge", "o/r#3->o/r#1"]);
    assert_eq!(run.status(), 0, "{}", run.describe());
    assert_eq!(fixture.patches(), 0);
}

#[test]
fn remove_edge_repairs_a_reference_outside_the_scope() {
    let mut state = chain();
    state["issues"]["o/r#5"]["body"] = json!(task("o/r#5", &["x/y#7", "o/r#1"]));
    let fixture = Fixture::new(&state);
    let run = fixture.run(&["--remove-edge", "x/y#7->o/r#5"]);
    assert_eq!(run.status(), 0, "{}", run.describe());
    assert_eq!(fixture.patches(), 1);
    assert_eq!(fixture.body("o/r#5"), task("o/r#5", &["o/r#1"]));
    let edit = run.edge_edit().expect("an edge_edit line");
    assert_eq!(edit["type"], "remove_blocked_by");
    assert_eq!(edit["changed"], true);
    // The out-of-scope parent is never read.
    assert!(
        !fixture
            .calls()
            .iter()
            .any(|a| a.iter().any(|x| x.contains("x/y") || x == "owner=x")),
        "{:?}",
        fixture.calls()
    );
}

// The command line.

#[test]
fn edit_arguments_are_checked_before_the_run_starts() {
    let fixture = Fixture::new(&chain());
    for args in [
        &["--add-edge", "o/r#1->o/r#1"][..],
        &["--add-edge", "1->2"],
        &[
            "--add-edge",
            "o/r#1->o/r#5",
            "--remove-edge",
            "o/r#1->o/r#5",
        ],
        &[],
        &["--add-edge", "o/r#1->o/r#5", "--offline"],
        &["--add-edge", "o/r#1->o/r#5", "--capture-bundle"],
        &["--add-edge", "o/r#1->o/r#5", "--from-bundle", "b.json"],
    ] {
        let run = fixture.run(args);
        assert_eq!(run.status(), 3, "{args:?}: {}", run.describe());
        assert_eq!(run.stdout(), Vec::<Value>::new());
    }
    assert_eq!(fixture.calls(), Vec::<Vec<String>>::new());
}

#[test]
fn edit_help_describes_the_edge_edit_result() {
    let fixture = Fixture::new(&chain());
    let run = fixture.run(&["--help"]);
    assert_eq!(run.status(), 0, "{}", run.describe());
    let stdout = run.stdout();
    let command = stdout
        .iter()
        .find(|l| l["event"] == "command")
        .expect("a command line");
    assert_eq!(command["name"], "edit");
    assert!(
        command["effects"]["writes"]
            .as_array()
            .is_some_and(|w| !w.is_empty())
    );
    assert!(
        stdout
            .iter()
            .any(|l| l["event"] == "schema" && l["id"] == "taskalisk.edge_edit")
    );
}
