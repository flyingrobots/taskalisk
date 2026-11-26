//! Capturing a live plan's observation bundle and replanning from it with
//! reads disabled (flyingrobots/taskalisk#59), against the fake `gh`
//! (`tests/fake_gh.py`) and a temporary git repository, as `tests/cli.rs`
//! runs the binary.
//!
//! "Reads disabled" is proven, not assumed: a replay runs with a `gh` and a
//! `git` first on `PATH` that log every call, and both logs stay empty.
#![cfg(unix)]

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};

use issue_dag_bundle::{Evaluator, evaluate, load};
use serde_json::{Value, json};

static NEXT: AtomicUsize = AtomicUsize::new(0);

/// A token value no adapter needs, planted where the bundle would carry it.
const TOKEN: &str = "zz9tok0123";

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("the repository root")
}

/// A fake GitHub, a git repository, and a `bin/` whose `gh` and `git` log
/// every call and answer nothing, for runs that must read nothing.
struct Fixture {
    dir: PathBuf,
}

impl Fixture {
    fn new(state: &str) -> Self {
        let dir = std::env::temp_dir().join(format!(
            "taskalisk-replay-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("bin")).expect("a temporary directory");
        fs::create_dir_all(dir.join("noread")).expect("a temporary directory");
        let dir = dir.canonicalize().expect("a canonical directory");
        let script = |path: PathBuf, text: String| {
            fs::write(&path, text).expect("a script");
            fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).expect("executable");
        };
        script(
            dir.join("bin/gh"),
            format!(
                "#!/bin/sh\nexec python3 '{}' \"$@\"\n",
                root().join("tests/fake_gh.py").display()
            ),
        );
        // The same fake gh, and a git that logs and fails: a replay that
        // reached either would leave a line in its log.
        script(
            dir.join("noread/gh"),
            format!(
                "#!/bin/sh\nexec python3 '{}' \"$@\"\n",
                root().join("tests/fake_gh.py").display()
            ),
        );
        script(
            dir.join("noread/git"),
            format!(
                "#!/bin/sh\necho \"git $*\" >> '{}'\nexit 1\n",
                dir.join("git.log").display()
            ),
        );
        fs::write(dir.join("state.json"), python_state(state)).expect("the state");
        fs::write(dir.join("log"), "").expect("the gh log");
        fs::write(dir.join("git.log"), "").expect("the git log");
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
            &["branch", "task/2-home-two"],
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

    fn repo(&self) -> String {
        self.dir.join("repo").to_str().expect("UTF-8").to_owned()
    }

    /// The binary, run from `cwd` under the fixture, with `bin` first on
    /// `PATH`, and `env` set.
    fn run(&self, bin: &str, cwd: &str, args: &[&str], env: &[(&str, &str)]) -> Run {
        let cwd = self.dir.join(cwd);
        fs::create_dir_all(&cwd).expect("the working directory");
        let mut path = self.dir.join(bin).into_os_string();
        path.push(":");
        path.push(std::env::var_os("PATH").unwrap_or_default());
        let mut command = Command::new(env!("CARGO_BIN_EXE_taskalisk"));
        command
            .current_dir(&cwd)
            .env("PATH", path)
            .env("FAKE_GH_STATE", self.dir.join("state.json"))
            .env("FAKE_GH_LOG", self.dir.join("log"))
            .stdin(Stdio::null())
            .args(args);
        for name in [
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "GH_ENTERPRISE_TOKEN",
            "GITHUB_ENTERPRISE_TOKEN",
        ] {
            command.env_remove(name);
        }
        for (key, value) in env {
            command.env(key, value);
        }
        let output = command.output().expect("the binary runs");
        Run { output, cwd }
    }

    /// A live plan of the fixture's repository.
    fn live(&self, cwd: &str, args: &[&str]) -> Run {
        let repo = self.repo();
        let mut all = vec!["plan", "--repo", repo.as_str()];
        all.extend_from_slice(args);
        self.run("bin", cwd, &all, &[])
    }

    /// A replay with reads disabled: the logging `gh` and `git` first on
    /// `PATH`, both logs emptied first.
    fn replay(&self, cwd: &str, args: &[&str]) -> Run {
        fs::write(self.dir.join("log"), "").expect("the gh log");
        fs::write(self.dir.join("git.log"), "").expect("the git log");
        let mut all = vec!["plan"];
        all.extend_from_slice(args);
        self.run("noread", cwd, &all, &[])
    }

    /// What the replay's `gh` and `git` were asked, which must be nothing.
    fn reads(&self) -> String {
        fs::read_to_string(self.dir.join("log")).expect("the gh log")
            + &fs::read_to_string(self.dir.join("git.log")).expect("the git log")
    }

    /// Changes the fake GitHub's state with `change`.
    fn change(&self, change: impl FnOnce(&mut Value)) {
        let path = self.dir.join("state.json");
        let mut state: Value =
            serde_json::from_str(&fs::read_to_string(&path).expect("the state")).expect("JSON");
        change(&mut state);
        fs::write(&path, state.to_string()).expect("the state");
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
    }
}

fn python_state(expression: &str) -> String {
    let out = Command::new("python3")
        .current_dir(root().join("tests"))
        .args([
            "-c",
            &format!(
                "import json\nfrom golden_scenarios import *\nfrom test_taskalisk import *\nprint(json.dumps({expression}))"
            ),
        ])
        .output()
        .expect("python3 runs");
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).expect("UTF-8")
}

struct Run {
    output: Output,
    cwd: PathBuf,
}

impl Run {
    fn status(&self) -> i32 {
        self.output.status.code().expect("an exit status")
    }

    fn stdout(&self) -> Vec<Value> {
        parse(&self.output.stdout)
    }

    fn stderr(&self) -> Vec<Value> {
        parse(&self.output.stderr)
    }

    fn receipt(&self) -> Vec<Value> {
        let boot = &self.stdout()[0];
        let path = boot["paths"]["receipt"].as_str().expect("a receipt path");
        parse(&fs::read(path).expect("the receipt"))
    }

    /// The receipt directory, `.parley/receipts/`.
    fn receipts(&self) -> PathBuf {
        self.cwd.join(".parley/receipts")
    }

    /// The receipt step that records the capture.
    fn capture(&self) -> Value {
        self.receipt()
            .into_iter()
            .find(|l| l["detail"]["bundle"]["path"].is_string())
            .unwrap_or_else(|| panic!("no capture step: {}", self.explain()))["detail"]
            .clone()
    }

    /// A captured file, by the path the capture step names.
    fn captured(&self, which: &str) -> PathBuf {
        let detail = self.capture();
        self.receipts()
            .join(detail[which]["path"].as_str().expect("a path"))
    }

    fn explain(&self) -> String {
        format!(
            "exit {:?}\nstdout:\n{}\nstderr:\n{}",
            self.output.status.code(),
            String::from_utf8_lossy(&self.output.stdout),
            String::from_utf8_lossy(&self.output.stderr)
        )
    }

    fn errors(&self) -> Vec<Value> {
        self.stderr()
            .into_iter()
            .filter(|l| l["_schema"]["id"] == "parley.error")
            .collect()
    }
}

fn parse(bytes: &[u8]) -> Vec<Value> {
    std::str::from_utf8(bytes)
        .expect("UTF-8")
        .lines()
        .map(|line| serde_json::from_str(line).expect("each line is JSON"))
        .collect()
}

fn schema(line: &Value) -> &str {
    line["_schema"]["id"].as_str().unwrap_or_default()
}

/// What a plan decided, without what only a display shows (titles, URLs,
/// branches) and without the run's envelope: the plan line's outcome,
/// frontier and batch, and each node, edge, wave, batch and finding line.
fn decided(lines: &[Value]) -> Vec<Value> {
    /// What only a display shows, at any depth.
    fn strip(value: &mut Value) {
        match value {
            Value::Object(object) => {
                for key in ["title", "url", "recoverable_branches"] {
                    object.remove(key);
                }
                object.values_mut().for_each(strip);
            }
            Value::Array(items) => items.iter_mut().for_each(strip),
            _ => {}
        }
    }
    lines
        .iter()
        .filter(|l| schema(l).starts_with("taskalisk."))
        .map(|l| {
            let mut l = l.clone();
            let object = l.as_object_mut().expect("an object");
            // The envelope, and the plan line's digest of the shown document.
            for key in ["t", "seq", "run", "artifact_hash"] {
                object.remove(key);
            }
            strip(&mut l);
            l
        })
        .collect()
}

/// Two plans decided the same, line by line.
fn assert_same_plan(replayed: &[Value], captured: &[Value]) {
    let (replayed, captured) = (decided(replayed), decided(captured));
    for (r, c) in replayed.iter().zip(&captured) {
        assert_eq!(r.to_string(), c.to_string(), "a line differs");
    }
    assert_eq!(
        replayed.len(),
        captured.len(),
        "the number of lines differs"
    );
}

fn validate(lines: &[Value]) {
    let mut child = Command::new("python3")
        .current_dir(root().join("tests"))
        .arg("validate_lines.py")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("python3 runs");
    let text: String = lines.iter().map(|l| l.to_string() + "\n").collect();
    std::io::Write::write_all(child.stdin.as_mut().expect("stdin"), text.as_bytes())
        .expect("the lines are written");
    let out = child.wait_with_output().expect("the validator ends");
    assert!(
        out.status.success(),
        "lines do not validate:\n{}",
        String::from_utf8_lossy(&out.stdout)
    );
}

fn evaluator() -> Evaluator {
    Evaluator {
        name: "taskalisk".to_owned(),
        version: env!("CARGO_PKG_VERSION").to_owned(),
    }
}

#[test]
fn a_capture_writes_the_bundle_the_plan_was_made_from() {
    let fixture = Fixture::new("rich_state()");
    let run = fixture.live("live", &["--capture-bundle"]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    let detail = run.capture();
    let run_id = run.stdout()[0]["run"]
        .as_str()
        .expect("a run id")
        .to_owned();
    // Beside the receipt, in the run's own directory, which retention
    // deletes with it, and which .parley/.gitignore keeps out of git.
    assert_eq!(detail["bundle"]["path"], format!("{run_id}/bundle.json"));
    assert_eq!(
        detail["evaluation"]["path"],
        format!("{run_id}/evaluation.json")
    );
    let text = fs::read_to_string(run.captured("bundle")).expect("the bundle");
    assert_eq!(
        detail["bundle"]["sha256"].as_str().map(str::len),
        Some(64),
        "{detail}"
    );
    // The bundle loader reads it, and it holds every slot the run reads
    // (OB14): an offline plan from it is not missing anything.
    let bundle = load(&text).expect("a bundle");
    assert_eq!(bundle.parameters.home.to_string(), "flyingrobots/geordi");
    let record = evaluate(&text, &evaluator()).expect("every slot the run reads");
    assert_eq!(record.result()["outcome"], "planned");
    // The evaluation record retains the bundle, whole.
    let saved: Value =
        serde_json::from_str(&fs::read_to_string(run.captured("evaluation")).expect("the record"))
            .expect("JSON");
    assert_eq!(saved["record"], "taskalisk-evaluation/1");
    assert_eq!(
        saved["observations"]["value"],
        serde_json::from_str::<Value>(&text).expect("JSON")
    );
    assert_eq!(&saved["result"], record.result());
    // The receipt itself still holds no issue body.
    let receipt = fs::read_to_string(run.stdout()[0]["paths"]["receipt"].as_str().expect("path"))
        .expect("the receipt");
    assert!(!receipt.contains("```yaml"), "a body reached the receipt");
    // The bundle does: it is the run's whole input.
    assert!(text.contains("```yaml"));
    // But never a stranger's body: it is not read (threat model C3, C15).
    let value: Value = serde_json::from_str(&text).expect("JSON");
    let stranger = &value["observations"]["issues"]["flyingrobots/geordi#77"]["value"];
    assert_eq!(stranger["author_association"], "NONE", "{stranger}");
    assert!(stranger.get("body").is_none(), "{stranger}");
}

#[test]
fn capture_is_off_by_default() {
    let fixture = Fixture::new("rich_state()");
    let run = fixture.live("live", &[]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    let receipts = run.receipts();
    let dirs: Vec<PathBuf> = fs::read_dir(&receipts)
        .expect("the receipts")
        .map(|e| e.expect("an entry").path())
        .filter(|p| p.is_dir())
        .collect();
    assert!(dirs.is_empty(), "nothing captured: {dirs:?}");
}

#[test]
fn a_replay_with_reads_disabled_gives_the_captured_plan_after_live_state_changed() {
    let fixture = Fixture::new("rich_state()");
    let captured = fixture.live("live", &["--sem-capacity", "gpu=1", "--capture-bundle"]);
    assert_eq!(captured.status(), 0, "{}", captured.explain());
    let bundle = captured.captured("bundle");

    // Live state moves on: the first frontier task closes.
    fixture.change(|state| {
        state["issues"]["flyingrobots/geordi#3"]["state"] = json!("closed");
        state["issues"]["flyingrobots/geordi#3"]["state_reason"] = json!("completed");
    });
    let moved = fixture.live("moved", &["--sem-capacity", "gpu=1"]);
    assert_eq!(moved.status(), 0, "{}", moved.explain());
    assert_ne!(
        decided(&moved.stdout()),
        decided(&captured.stdout()),
        "the live plan changed"
    );

    let replay = fixture.replay(
        "replay",
        &["--from-bundle", bundle.to_str().expect("UTF-8")],
    );
    assert_eq!(replay.status(), 0, "{}", replay.explain());
    assert_eq!(fixture.reads(), "", "a replay read gh or git");
    assert_same_plan(&replay.stdout(), &captured.stdout());
    let plan = &replay.stdout()[1];
    assert_eq!(schema(plan), "taskalisk.plan");
    assert_eq!(plan["frontier"], captured.stdout()[1]["frontier"]);
}

#[test]
fn a_replayed_plan_writes_lines_that_validate() {
    let fixture = Fixture::new("plan_state()");
    let captured = fixture.live(
        "live",
        &["--root", "flyingrobots/geordi#9", "--capture-bundle"],
    );
    assert_eq!(captured.status(), 0, "{}", captured.explain());
    let bundle = captured.captured("bundle");
    let replay = fixture.replay(
        "replay",
        &["--from-bundle", bundle.to_str().expect("UTF-8")],
    );
    assert_eq!(replay.status(), 0, "{}", replay.explain());
    assert_eq!(fixture.reads(), "");
    validate(&replay.stdout());
    validate(&replay.receipt());
    // The receipt names the bundle as the run's declared input.
    let head = &replay.receipt()[0];
    assert_eq!(head["inputs"][0]["role"], "observations");
    assert_eq!(head["effects"]["network"], false);
}

#[test]
fn an_evaluation_record_replays_offline() {
    let fixture = Fixture::new("rich_state()");
    let captured = fixture.live("live", &["--capture-bundle"]);
    assert_eq!(captured.status(), 0, "{}", captured.explain());
    let record = captured.captured("evaluation");
    fixture.change(|state| {
        state["issues"]["flyingrobots/geordi#3"]["state"] = json!("closed");
    });

    let replay = fixture.replay(
        "replay",
        &["--from-record", record.to_str().expect("UTF-8")],
    );
    assert_eq!(replay.status(), 0, "{}", replay.explain());
    assert_eq!(fixture.reads(), "", "a replay read gh or git");
    assert_same_plan(&replay.stdout(), &captured.stdout());
    let step = replay
        .receipt()
        .into_iter()
        .find(|l| l["detail"]["replay"].is_string())
        .unwrap_or_else(|| panic!("no replay step: {}", replay.explain()));
    assert_eq!(step["detail"]["replay"], "reproduced");

    // A record whose result is not what its bundle plans: the difference
    // is reported, and no plan is written from it.
    let mut tampered: Value =
        serde_json::from_str(&fs::read_to_string(&record).expect("the record")).expect("JSON");
    tampered["result"]["batch"] = json!([]);
    let path = fixture.dir.join("tampered.json");
    fs::write(&path, tampered.to_string()).expect("a record");
    let replay = fixture.replay(
        "tampered",
        &["--from-record", path.to_str().expect("UTF-8")],
    );
    assert_eq!(replay.status(), 2, "{}", replay.explain());
    assert_eq!(replay.errors()[0]["code"], "evaluation.differs");
    assert!(
        replay
            .stdout()
            .iter()
            .all(|l| schema(l) != "taskalisk.plan")
    );
}

#[test]
fn a_record_that_did_not_retain_its_bundle_cannot_replay() {
    let fixture = Fixture::new("rich_state()");
    let live = fixture.live("live", &[]);
    assert_eq!(live.status(), 0, "{}", live.explain());
    let record = live
        .receipt()
        .into_iter()
        .find_map(|l| {
            (l["detail"]["record"]["record"] == "taskalisk-evaluation/1")
                .then(|| l["detail"]["record"].clone())
        })
        .expect("the receipt's record");
    let path = fixture.dir.join("unretained.json");
    fs::write(&path, record.to_string()).expect("a record");
    let replay = fixture.replay("replay", &["--from-record", path.to_str().expect("UTF-8")]);
    assert_eq!(replay.status(), 2, "{}", replay.explain());
    assert_eq!(fixture.reads(), "");
    assert_eq!(replay.errors()[0]["code"], "evaluation.unavailable");
    assert!(
        replay
            .stdout()
            .iter()
            .all(|l| schema(l) != "taskalisk.plan")
    );
}

/// A captured bundle as JSON, to take apart.
fn captured_bundle(fixture: &Fixture) -> Value {
    let captured = fixture.live("live", &["--capture-bundle"]);
    assert_eq!(captured.status(), 0, "{}", captured.explain());
    serde_json::from_str(&fs::read_to_string(captured.captured("bundle")).expect("the bundle"))
        .expect("JSON")
}

#[test]
fn a_missing_slot_makes_the_bundle_unusable_never_empty() {
    let fixture = Fixture::new("rich_state()");
    let mut bundle = captured_bundle(&fixture);
    // OB5: the run reads echo#5's issue slot; drop it.
    bundle["observations"]["issues"]
        .as_object_mut()
        .expect("issues")
        .remove("flyingrobots/echo#5")
        .expect("echo#5 was read");
    let path = fixture.dir.join("missing.json");
    fs::write(&path, bundle.to_string()).expect("a bundle");
    let replay = fixture.replay("replay", &["--from-bundle", path.to_str().expect("UTF-8")]);
    assert_eq!(replay.status(), 2, "{}", replay.explain());
    assert_eq!(fixture.reads(), "");
    let errors = replay.errors();
    assert_eq!(errors.len(), 1, "{}", replay.explain());
    assert_eq!(errors[0]["code"], "bundle.incomplete");
    assert_eq!(
        errors[0]["detail"]["missing"],
        json!(["issues", "flyingrobots/echo#5"])
    );
    assert!(
        replay
            .stdout()
            .iter()
            .all(|l| schema(l) != "taskalisk.plan")
    );
}

#[test]
fn an_unavailable_slot_makes_the_run_incomplete_never_empty() {
    let fixture = Fixture::new("rich_state()");
    let mut bundle = captured_bundle(&fixture);
    bundle["observations"]["issues"]["flyingrobots/echo#5"] =
        json!({"unavailable": "HTTP 502 from the issues endpoint"});
    let path = fixture.dir.join("unavailable.json");
    fs::write(&path, bundle.to_string()).expect("a bundle");
    let replay = fixture.replay("replay", &["--from-bundle", path.to_str().expect("UTF-8")]);
    assert_eq!(replay.status(), 2, "{}", replay.explain());
    assert_eq!(fixture.reads(), "");
    let errors = replay.errors();
    assert_eq!(errors.len(), 1, "{}", replay.explain());
    assert_eq!(errors[0]["code"], "observation.unavailable");
    assert_eq!(
        errors[0]["detail"]["unavailable"],
        "HTTP 502 from the issues endpoint"
    );
    assert!(
        replay
            .stdout()
            .iter()
            .all(|l| schema(l) != "taskalisk.plan")
    );
}

#[test]
fn a_file_that_is_not_a_bundle_is_a_reported_error() {
    let fixture = Fixture::new("plan_state()");
    let path = fixture.dir.join("not-a-bundle.json");
    fs::write(&path, r#"{"bundle": "issue-dag-observations/9"}"#).expect("a file");
    let replay = fixture.replay("replay", &["--from-bundle", path.to_str().expect("UTF-8")]);
    assert_eq!(replay.status(), 2, "{}", replay.explain());
    assert_eq!(replay.errors()[0]["code"], "bundle.invalid");
    let absent = fixture.dir.join("absent.json");
    let replay = fixture.replay(
        "absent",
        &["--from-bundle", absent.to_str().expect("UTF-8")],
    );
    assert_eq!(replay.status(), 2, "{}", replay.explain());
    assert_eq!(replay.errors()[0]["code"], "bundle.unreadable");
    assert_eq!(fixture.reads(), "");
}

/// The largest bundle or record a replay reads: 64 MiB.
const READ_LIMIT: u64 = 64 * 1024 * 1024;

#[test]
fn a_file_over_the_read_limit_is_refused_unread() {
    let fixture = Fixture::new("plan_state()");
    // A sparse file one byte over the limit: refused before it is read.
    let path = fixture.dir.join("huge.json");
    fs::File::create(&path)
        .and_then(|f| f.set_len(READ_LIMIT + 1))
        .expect("a sparse file");
    for (flag, code) in [
        ("--from-bundle", "bundle.unreadable"),
        ("--from-record", "evaluation.unreadable"),
    ] {
        let replay = fixture.replay("huge", &[flag, path.to_str().expect("UTF-8")]);
        assert_eq!(replay.status(), 2, "{}", replay.explain());
        let errors = replay.errors();
        assert_eq!(errors[0]["code"], code, "{}", replay.explain());
        assert_eq!(
            errors[0]["detail"]["limit"],
            READ_LIMIT,
            "{}",
            replay.explain()
        );
    }
    // A file at the limit is read (and here is not JSON).
    fs::File::create(&path)
        .and_then(|f| f.set_len(READ_LIMIT))
        .expect("a sparse file");
    let replay = fixture.replay("limit", &["--from-bundle", path.to_str().expect("UTF-8")]);
    assert_eq!(replay.status(), 2, "{}", replay.explain());
    assert_eq!(replay.errors()[0]["code"], "bundle.invalid");
    assert_eq!(fixture.reads(), "");
}

#[test]
fn with_reads_disabled_and_no_bundle_the_command_exits_2() {
    let fixture = Fixture::new("plan_state()");
    let repo = fixture.repo();
    let run = fixture.replay("offline", &["--offline", "--repo", &repo]);
    assert_eq!(run.status(), 2, "{}", run.explain());
    assert_eq!(fixture.reads(), "", "--offline read gh or git");
    assert_eq!(run.errors()[0]["code"], "plan.reads_disabled");
}

#[test]
fn a_replay_refuses_the_flags_its_bundle_already_answers() {
    let fixture = Fixture::new("plan_state()");
    for extra in [
        &["--root", "flyingrobots/geordi#9"][..],
        &["--sem-capacity", "gpu=1"],
        &["--trust", "dev"],
        &["--trust-owner", "o"],
        &["--trust-repo", "o/r"],
        &["--trust-codeowners"],
        &["--repo", "."],
        &["--capture-bundle"],
        &["--from-record", "x.json"],
    ] {
        let mut args = vec!["--from-bundle", "x.json"];
        args.extend_from_slice(extra);
        let run = fixture.replay("refused", &args);
        assert_eq!(run.status(), 3, "{extra:?}: {}", run.explain());
        assert_eq!(run.stderr()[0]["code"], "startup.arguments_invalid");
    }
    let run = fixture.replay("refused", &["--offline", "--capture-bundle"]);
    assert_eq!(run.status(), 3, "{}", run.explain());
}

#[test]
fn a_planted_token_never_reaches_a_bundle() {
    let fixture = Fixture::new("rich_state()");
    // The token in a trusted issue's body, as GitHub would return it, and
    // in the environment as the gh token.
    fixture.change(|state| {
        let body = state["issues"]["flyingrobots/geordi#3"]["body"]
            .as_str()
            .expect("a body")
            .to_owned();
        state["issues"]["flyingrobots/geordi#3"]["body"] =
            json!(format!("{body}\nleaked: {TOKEN}\n"));
    });
    let repo = fixture.repo();
    let run = fixture.run(
        "bin",
        "live",
        &["plan", "--repo", &repo, "--capture-bundle"],
        &[("GH_TOKEN", TOKEN)],
    );
    assert_eq!(run.status(), 0, "{}", run.explain());
    let detail = run.capture();
    for which in ["bundle", "evaluation"] {
        let text = fs::read_to_string(run.captured(which)).expect("a captured file");
        assert!(!text.contains(TOKEN), "the token reached the {which}");
        assert!(text.contains("[redacted]"), "{which} was not redacted");
    }
    // The capture says where it redacted, so a replay that differs can be
    // told apart from a defect.
    assert!(
        detail["redacted"]
            .as_array()
            .is_some_and(|at| !at.is_empty()),
        "{detail}"
    );
    // The redacted bundle is still a bundle.
    let text = fs::read_to_string(run.captured("bundle")).expect("the bundle");
    load(&text).expect("a bundle");
}

#[test]
fn the_committed_bundle_of_this_repository_replays_offline() {
    let dir = root().join("tests/fixtures/bundles");
    let bundle = dir.join("flyingrobots-taskalisk.bundle.json");
    let text = fs::read_to_string(&bundle).expect("the committed bundle");
    let expected: Value = serde_json::from_str(
        &fs::read_to_string(dir.join("flyingrobots-taskalisk.result.json"))
            .expect("the committed result"),
    )
    .expect("JSON");
    // OB14: it holds every slot its run reads, and plans to the result the
    // live run recorded when it was captured.
    let record = evaluate(&text, &evaluator()).expect("every slot the run reads");
    assert_eq!(record.result(), &expected);
    // Nothing machine-local: no home directory, no absolute user path.
    for local in ["/Users/", "/home/", "C:\\"] {
        assert!(!text.contains(local), "the bundle holds {local}");
    }
    let fixture = Fixture::new("plan_state()");
    let replay = fixture.replay(
        "replay",
        &["--from-bundle", bundle.to_str().expect("UTF-8")],
    );
    assert_eq!(replay.status(), 0, "{}", replay.explain());
    assert_eq!(fixture.reads(), "");
    let plan = &replay.stdout()[1];
    assert_eq!(schema(plan), "taskalisk.plan");
    assert_eq!(plan["source"]["repository"], "flyingrobots/taskalisk");
}
