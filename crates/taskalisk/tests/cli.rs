//! The `taskalisk` binary's `plan` against the fake `gh` (`tests/fake_gh.py`,
//! found as `gh` on `PATH`, as `issue-dag-gh`'s own tests find it) and a
//! temporary git repository. Each fake GitHub is a state of
//! `tests/golden_scenarios.py`, the one the Python's captured runs use, so
//! the two implementations plan the same backlog.
#![cfg(unix)]

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};

use serde_json::{Map, Value, json};

static NEXT: AtomicUsize = AtomicUsize::new(0);

const HOME: &str = "flyingrobots/geordi";

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("the repository root")
}

/// A fake `gh` on `PATH`, its state, its log, and a git repository with one
/// commit and a branch that names issue 2.
struct Fixture {
    dir: PathBuf,
}

impl Fixture {
    /// A fixture whose GitHub is `state`, a Python expression over
    /// `golden_scenarios` and `test_taskalisk` (such as `rich_state()`).
    fn new(state: &str) -> Self {
        let dir = std::env::temp_dir().join(format!(
            "taskalisk-cli-{}-{}",
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
        fs::write(dir.join("state.json"), python_state(state)).expect("the state");
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
            &["branch", "task/2-home-two"],
            &["branch", "task/22-other"],
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

    fn repo(&self) -> PathBuf {
        self.dir.join("repo")
    }

    /// A command whose `gh` is the fake, run from `cwd` (receipts land there).
    fn command(&self, program: &Path, cwd: &Path) -> Command {
        let mut path = self.dir.join("bin").into_os_string();
        path.push(":");
        path.push(std::env::var_os("PATH").unwrap_or_default());
        let mut command = Command::new(program);
        command
            .current_dir(cwd)
            .env("PATH", path)
            .env("FAKE_GH_STATE", self.dir.join("state.json"))
            .env("FAKE_GH_LOG", self.dir.join("log"))
            .env("XDG_STATE_HOME", self.dir.join("state"))
            .stdin(Stdio::null());
        for name in [
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "GH_ENTERPRISE_TOKEN",
            "GITHUB_ENTERPRISE_TOKEN",
        ] {
            command.env_remove(name);
        }
        command
    }

    /// The Rust binary with `args`, from the fixture's directory `cwd`.
    fn run_in(&self, cwd: &str, args: &[&str]) -> Run {
        let cwd = self.dir.join(cwd);
        fs::create_dir_all(&cwd).expect("the working directory");
        let output = self
            .command(Path::new(env!("CARGO_BIN_EXE_taskalisk")), &cwd)
            .args(args)
            .output()
            .expect("the binary runs");
        Run { output, cwd }
    }

    /// The Rust binary planning the fixture's repository with `args`.
    fn plan(&self, args: &[&str]) -> Run {
        let repo = self.repo();
        let mut all = vec!["plan", "--repo", repo.to_str().expect("UTF-8")];
        all.extend_from_slice(args);
        self.run_in("rust", &all)
    }

    /// The Python compiler planning the same repository with `args`.
    fn python(&self, args: &[&str]) -> Run {
        let cwd = self.dir.join("python");
        fs::create_dir_all(&cwd).expect("the working directory");
        let output = self
            .command(Path::new("python3"), &cwd)
            .arg(root().join("skills/taskalisk/scripts/taskalisk.py"))
            .args(["plan", "--repo"])
            .arg(self.repo())
            .args(args)
            .output()
            .expect("python3 runs");
        Run { output, cwd }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.dir);
    }
}

/// The JSON of a fake GitHub state built by `tests/golden_scenarios.py`.
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

    fn text(&self) -> String {
        String::from_utf8(self.output.stdout.clone()).expect("UTF-8")
    }

    /// The receipt the bootstrap line names.
    fn receipt(&self) -> Vec<Value> {
        let boot = &self.stdout()[0];
        let path = boot["paths"]["receipt"].as_str().expect("a receipt path");
        parse(&fs::read(path).expect("the receipt"))
    }

    fn receipts(&self) -> Vec<PathBuf> {
        fs::read_dir(self.cwd.join(".parley/receipts")).map_or_else(
            |_| Vec::new(),
            |dir| {
                dir.map(|e| e.expect("an entry").path())
                    .filter(|p| p.extension().is_some_and(|x| x == "jsonl"))
                    .collect()
            },
        )
    }

    fn explain(&self) -> String {
        format!(
            "exit {:?}\nstdout:\n{}\nstderr:\n{}",
            self.output.status.code(),
            String::from_utf8_lossy(&self.output.stdout),
            String::from_utf8_lossy(&self.output.stderr)
        )
    }
}

fn parse(bytes: &[u8]) -> Vec<Value> {
    let text = std::str::from_utf8(bytes).expect("UTF-8");
    assert!(
        text.is_empty() || text.ends_with('\n'),
        "a stream ends without a line feed"
    );
    text.lines()
        .map(|line| {
            let value: Value = serde_json::from_str(line).expect("each line is JSON");
            assert!(value.is_object(), "each line is an object: {line}");
            value
        })
        .collect()
}

fn schema(line: &Value) -> &str {
    line["_schema"]["id"].as_str().unwrap_or_default()
}

fn of<'a>(lines: &'a [Value], id: &str) -> Vec<&'a Value> {
    lines.iter().filter(|l| schema(l) == id).collect()
}

/// Every line validates against the exact schema it names, by the vendored
/// writer's checker (`tests/validate_lines.py`).
fn assert_valid(lines: &[Value]) {
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

/// A line without its envelope (`t`, `seq`, `run`) and without `drop`.
fn payload(line: &Value, drop: &[&str]) -> Map<String, Value> {
    line.as_object()
        .expect("an object")
        .iter()
        .filter(|(k, _)| !["t", "seq", "run"].contains(&k.as_str()) && !drop.contains(&k.as_str()))
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect()
}

#[test]
fn a_live_plan_writes_lines_that_validate_and_a_receipt() {
    let fixture = Fixture::new("rich_state()");
    let run = fixture.plan(&["--sem-capacity", "gpu=1"]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    let out = run.stdout();
    let receipt = run.receipt();
    assert!(run.stderr().is_empty(), "{}", run.explain());
    assert_valid(&out);
    assert_valid(&receipt);

    // The bootstrap line first, the plan next, the end last.
    assert_eq!(schema(&out[0]), "parley.run.bootstrap");
    assert_eq!(out[0]["tool"], "taskalisk");
    assert_eq!(schema(&out[1]), "taskalisk.plan");
    let end = out.last().expect("an end line");
    assert_eq!(schema(end), "parley.end");
    assert_eq!(end["status"], 0);
    assert_eq!(end["receipt"], out[0]["paths"]["receipt"]);
    // One sequence across the streams and the receipt.
    let seqs: Vec<u64> = out
        .iter()
        .map(|l| l["seq"].as_u64().expect("seq"))
        .collect();
    assert!(seqs.windows(2).all(|w| w[0] < w[1]), "{seqs:?}");
    assert!(out.iter().all(|l| l["run"] == out[0]["run"]));

    let plan = &out[1];
    assert_eq!(plan["mode"], "github");
    assert_eq!(plan["outcome"], "compiled");
    assert_eq!(plan["ok"], true);
    assert_eq!(plan["source"]["repository"], HOME);
    assert_eq!(
        plan["frontier"],
        json!([
            "flyingrobots/geordi#3",
            "flyingrobots/echo#5",
            "flyingrobots/bunny#110"
        ])
    );

    // The display input came from the adapters: titles, URLs, branches.
    let node = |id: &str| {
        out.iter()
            .find(|l| {
                l["id"] == id && matches!(schema(l), "taskalisk.node" | "taskalisk.frontier_node")
            })
            .unwrap_or_else(|| panic!("no line for {id}"))
            .clone()
    };
    assert_eq!(node("flyingrobots/geordi#3")["title"], "Home three");
    assert_eq!(
        node("flyingrobots/echo#5")["url"],
        "https://github.com/flyingrobots/echo/issues/5"
    );
    assert_eq!(
        node("flyingrobots/geordi#2")["recoverable_branches"],
        json!(["task/2-home-two"])
    );
    assert_eq!(
        node("flyingrobots/geordi#1")["recoverable_branches"],
        json!([])
    );

    // The receipt: the head, the steps, a copy of every result, the inputs
    // with inv, the end.
    assert_eq!(schema(&receipt[0]), "parley.receipt.head");
    assert_eq!(receipt[0]["resolved"]["command"], "plan");
    for line in &out[1..] {
        assert!(receipt.contains(line), "the receipt lacks {line}");
    }
    let inputs = of(&receipt, "parley.receipt.inputs");
    assert_eq!(inputs.len(), 1);
    assert_eq!(inputs[0]["inputs"][0]["path"], "github:issues");
    assert!(inputs[0]["inv"].as_str().is_some_and(|inv| inv.len() == 64));
    assert_eq!(receipt.last(), Some(end));
    // No issue body enters the receipt.
    let text = fs::read_to_string(out[0]["paths"]["receipt"].as_str().expect("path"))
        .expect("the receipt");
    assert!(!text.contains("```yaml"), "a body reached the receipt");
    // The receipt directory is ignored by git.
    assert_eq!(
        fs::read_to_string(run.cwd.join(".parley/.gitignore")).expect("the .gitignore"),
        "*\n"
    );
}

#[test]
fn a_backlog_with_no_stranger_gives_lines_that_all_validate() {
    let fixture = Fixture::new("plan_state()");
    let run = fixture.plan(&["--root", "flyingrobots/geordi#9"]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    let (out, receipt) = (run.stdout(), run.receipt());
    assert!(of(&out, "taskalisk.finding").iter().all(|f| !matches!(
        f["code"].as_str(),
        Some("issue.untrusted" | "pull_request.untrusted")
    )));
    assert_valid(&out);
    assert_valid(&receipt);
}

#[test]
fn every_plan_records_its_evaluation_in_the_receipt() {
    let fixture = Fixture::new("rich_state()");
    let run = fixture.plan(&[]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    let receipt = run.receipt();
    let records: Vec<&Value> = receipt
        .iter()
        .filter(|l| l["detail"]["record"]["record"] == "taskalisk-evaluation/1")
        .collect();
    assert_eq!(records.len(), 1, "one evaluation record per plan");
    let record = &records[0]["detail"]["record"];
    assert_eq!(record["formats"], json!(["issue-dag/2"]));
    assert_eq!(record["profile"], "issue-dag-planning/2");
    assert_eq!(record["evaluator"]["name"], "taskalisk");
    assert_eq!(record["discovery"]["home"], HOME);
    assert_eq!(record["result"]["outcome"], "planned");
    // A live bundle is not retained until flyingrobots/taskalisk#59.
    assert!(record["observations"]["unavailable"].is_string());
}

#[test]
fn the_plan_matches_the_python_on_the_same_backlog() {
    let fixture = Fixture::new("rich_state()");
    let rust = fixture.plan(&["--sem-capacity", "gpu=1"]);
    let python = fixture.python(&["--sem-capacity", "gpu=1"]);
    assert_eq!(rust.status(), 0, "{}", rust.explain());
    assert_eq!(python.status(), 0, "{}", python.explain());
    // A linked pull request carries its URL, from `gh pr list`.
    let linked = rust
        .stdout()
        .iter()
        .find(|l| l["id"] == "flyingrobots/geordi#3")
        .expect("geordi#3")["linked_open_prs"]
        .clone();
    assert_eq!(
        linked[0]["url"],
        "https://github.com/flyingrobots/geordi/pull/8"
    );
    let strip = |line: &Value| payload(line, &["artifact_hash"]);
    let results = |run: &Run| -> Vec<Map<String, Value>> {
        run.stdout()
            .iter()
            .filter(|l| {
                matches!(
                    schema(l),
                    "taskalisk.plan"
                        | "taskalisk.frontier_node"
                        | "taskalisk.batch"
                        | "taskalisk.node"
                        | "taskalisk.wave"
                        | "taskalisk.edge"
                )
            })
            .map(strip)
            .collect()
    };
    assert_eq!(results(&rust), results(&python));
    // Findings: the same codes and subjects. The frontmatter messages (the
    // core's fixed text) are the renderer's documented difference; an
    // untrusted issue or pull request is the Python's line, its reasons
    // included (flyingrobots/taskalisk#46).
    let untrusted = |run: &Run| -> Vec<Map<String, Value>> {
        run.stdout()
            .iter()
            .filter(|l| {
                matches!(
                    l["code"].as_str(),
                    Some("issue.untrusted" | "pull_request.untrusted")
                )
            })
            .map(|l| payload(l, &[]))
            .collect()
    };
    assert!(!untrusted(&rust).is_empty(), "the backlog holds a stranger");
    assert_eq!(untrusted(&rust), untrusted(&python));
    let findings = |run: &Run| -> Vec<(Value, Value)> {
        run.stdout()
            .iter()
            .filter(|l| schema(l) == "taskalisk.finding")
            .map(|l| (l["code"].clone(), l["subject"].clone()))
            .collect()
    };
    assert_eq!(findings(&rust), findings(&python));
}

#[test]
fn equal_inputs_give_identical_output_but_for_the_run() {
    let fixture = Fixture::new("rich_state()");
    let normal = |run: &Run| -> Vec<Map<String, Value>> {
        run.stdout()
            .iter()
            .map(|line| {
                let mut p = payload(line, &["receipt"]);
                p.remove("paths");
                p.insert("seq".into(), line["seq"].clone());
                p
            })
            .collect()
    };
    let first = fixture.plan(&["--sem-capacity", "gpu=1"]);
    let second = fixture.plan(&["--sem-capacity", "gpu=1"]);
    assert_eq!(first.status(), 0, "{}", first.explain());
    assert_ne!(first.stdout()[0]["run"], second.stdout()[0]["run"]);
    assert_eq!(normal(&first), normal(&second));
    // The result lines themselves are the same bytes.
    let results = |run: &Run| -> Vec<String> {
        run.text()
            .lines()
            .filter(|l| l.contains("\"taskalisk."))
            .map(|l| {
                let v: Value = serde_json::from_str(l).expect("JSON");
                serde_json::to_string(&payload(&v, &[])).expect("JSON")
            })
            .collect()
    };
    assert_eq!(results(&first), results(&second));
}

#[test]
fn a_failed_gh_read_exits_2_with_an_error_and_no_plan() {
    let fixture = Fixture::new("gh_failure_state()");
    let run = fixture.plan(&[]);
    assert_eq!(run.status(), 2, "{}", run.explain());
    let (out, err) = (run.stdout(), run.stderr());
    assert_valid(&out);
    assert_valid(&err);
    assert_valid(&run.receipt());
    assert!(
        of(&out, "taskalisk.plan").is_empty(),
        "no plan from a partial read"
    );
    assert_eq!(out.last().expect("end")["status"], 2);
    let errors = of(&err, "parley.error");
    assert_ne!(errors.len(), 0, "{}", run.explain());
    for error in errors {
        assert_eq!(error["code"], "gh.command_failed");
        assert_eq!(error["retryable"], true);
        assert_eq!(error["detail"]["phase"], "discovery");
        assert!(
            error["detail"]["source"]
                .as_str()
                .is_some_and(|s| s.starts_with("gh api graphql"))
        );
    }
    // The input could not be read whole, so there is no inv.
    let inputs = run.receipt();
    let inputs = of(&inputs, "parley.receipt.inputs");
    assert_eq!(inputs[0]["inputs"][0]["error"], "input.unreadable");
    assert!(inputs[0].get("inv").is_none());
}

#[test]
fn a_repository_git_cannot_read_exits_2() {
    let fixture = Fixture::new("plan_state()");
    let elsewhere = fixture.dir.join("not-a-repository");
    fs::create_dir_all(&elsewhere).expect("a directory");
    let run = fixture.run_in(
        "rust",
        &["plan", "--repo", elsewhere.to_str().expect("UTF-8")],
    );
    assert_eq!(run.status(), 2, "{}", run.explain());
    let err = run.stderr();
    assert_valid(&err);
    let errors = of(&err, "parley.error");
    assert_eq!(errors.len(), 1, "{}", run.explain());
    assert_eq!(errors[0]["code"], "git.command_failed");
    assert_eq!(of(&run.stdout(), "taskalisk.plan").len(), 0);
}

#[test]
fn a_graph_that_cannot_be_ranked_is_a_reported_error() {
    let fixture = Fixture::new(
        "(lambda s: (s['issues'][f'{ECHO}#5'].update(body=fm(f'{ECHO}#5', blocked_by=[f'{HOME}#2'])), s)[1])(plan_state())",
    );
    let run = fixture.plan(&["--root", "flyingrobots/geordi#9"]);
    assert_eq!(run.status(), 2, "{}", run.explain());
    let (out, err) = (run.stdout(), run.stderr());
    assert_valid(&out);
    assert_valid(&err);
    let plan = of(&out, "taskalisk.plan");
    assert_eq!(plan[0]["outcome"], "cycle");
    assert_eq!(plan[0]["ok"], false);
    let errors = of(&err, "parley.error");
    assert_eq!(errors.len(), 1);
    assert_eq!(errors[0]["code"], "graph.cycle");
    let cyclic: Vec<Value> = of(&out, "taskalisk.finding")
        .iter()
        .filter(|f| f["code"] == "graph.cyclic_node")
        .map(|f| f["subject"].clone())
        .collect();
    assert_eq!(
        errors[0]["detail"]["cyclic_nodes"],
        Value::Array(cyclic.clone())
    );
    for id in [
        "flyingrobots/echo#5",
        "flyingrobots/geordi#1",
        "flyingrobots/geordi#2",
    ] {
        assert!(cyclic.contains(&json!(id)), "{id} in {cyclic:?}");
    }
}

#[test]
fn a_root_outside_the_scope_is_a_command_error_with_a_receipt() {
    let fixture = Fixture::new("plan_state()");
    let run = fixture.plan(&["--root", "strangers/elsewhere#1"]);
    assert_eq!(run.status(), 2, "{}", run.explain());
    let err = run.stderr();
    assert_valid(&err);
    assert_eq!(of(&err, "parley.error")[0]["code"], "root.out_of_scope");
    assert_eq!(run.receipts().len(), 1);
}

#[test]
fn a_usage_error_exits_3_with_one_startup_line_and_no_receipt() {
    let fixture = Fixture::new("plan_state()");
    let repo = fixture.repo();
    let repo = repo.to_str().expect("UTF-8");
    let cases: &[&[&str]] = &[
        &["plan", "--repo", repo, "--bogus"],
        &["plan", "--repo", repo, "--from"],
        &["plan", "--repo", repo, "--root", "12"],
        &["plan", "--repo", repo, "--root"],
        &["plan", "--repo", repo, "--sem-capacity", "gpu=0"],
        &["plan", "--repo", repo, "--trust-owner", "a/b"],
        &["plan", "--repo", repo, "--trust-repo", "nope"],
        &["plan", "--repo", repo, "stray"],
        // A flag the core cannot honour yet is refused, never ignored.
        &["plan", "--repo", repo, "--emit-mermaid"],
        &["plan", "--repo", repo, "--emit-roadmap"],
        &["plan", "--repo", repo, "--since-last"],
        &["plan", "--repo", repo, "--compare-relationships"],
        &["plan", "--repo", repo, "--min-confidence", "0.5"],
        &["plan", "--repo", repo, "--milestone", "m"],
        &["plan", "--repo", repo, "--dry-run"],
        &["plan", "--repo", repo, "--schema"],
        &["plan", "--repo", repo, "--add-edge", "o/r#1->o/r#2"],
        &["plan", "--repo", repo, "--verify-dag", "x.json"],
        // Commands the binary does not have yet.
        &["edit", "--repo", repo],
        &["verify", "--repo", repo],
        &["inventory", "--repo", repo],
        &["--repo", repo],
    ];
    for (n, args) in cases.iter().enumerate() {
        let dir = format!("usage-{n}");
        let run = fixture.run_in(&dir, args);
        assert_eq!(run.status(), 3, "{args:?}: {}", run.explain());
        assert!(run.output.stdout.is_empty(), "{args:?}: {}", run.explain());
        let err = run.stderr();
        assert_eq!(err.len(), 1, "{args:?}: {}", run.explain());
        assert_eq!(schema(&err[0]), "parley.startup.failed");
        assert_eq!(err[0]["seq"], 0);
        assert_valid(&err);
        assert!(
            run.receipts().is_empty(),
            "{args:?}: a usage error has no receipt"
        );
    }
}

#[test]
fn the_1x_mode_flag_and_an_equals_sign_select_the_same_plan() {
    let fixture = Fixture::new("plan_state()");
    let repo = format!("--repo={}", fixture.repo().display());
    let named = fixture.run_in("named", &["plan", &repo]);
    let inferred = fixture.run_in("inferred", &[&repo, "--from-github"]);
    assert_eq!(named.status(), 0, "{}", named.explain());
    assert_eq!(inferred.status(), 0, "{}", inferred.explain());
    assert_eq!(
        of(&named.stdout(), "taskalisk.plan")[0]["artifact_hash"],
        of(&inferred.stdout(), "taskalisk.plan")[0]["artifact_hash"]
    );
}

#[test]
fn human_prints_prose_and_keeps_the_receipt() {
    let fixture = Fixture::new("rich_state()");
    let run = fixture.plan(&["--sem-capacity", "gpu=1", "--human"]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    let text = run.text();
    let lines: Vec<&str> = text.lines().collect();
    assert_eq!(
        lines[0],
        "flyingrobots/geordi: compiled, 8 open node(s), 3 on the frontier, a batch of 1, critical path 4"
    );
    assert!(
        text.contains("   1   1010  flyingrobots/geordi#3            wip          Home three\n")
    );
    assert!(
        text.contains(
            "batch: flyingrobots/geordi#3\n  skipped flyingrobots/echo#5: holds conflict\n"
        )
    );
    assert!(!text.contains("{\""), "no JSON on stdout under --human");
    // The receipt is the JSON one, wherever --human sends the prose.
    let receipts = run.receipts();
    assert_eq!(receipts.len(), 1);
    let receipt = parse(&fs::read(&receipts[0]).expect("the receipt"));
    assert_valid(&receipt);
    assert_eq!(of(&receipt, "taskalisk.plan").len(), 1);
}

#[test]
fn help_describes_the_plan_command_and_its_schemas() {
    let fixture = Fixture::new("plan_state()");
    let run = fixture.run_in("help", &["plan", "--help"]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    let out = run.stdout();
    assert_valid(&out);
    let commands = of(&out, "parley.command");
    assert_eq!(commands.len(), 1);
    assert_eq!(commands[0]["name"], "plan");
    let schemas: Vec<&str> = of(&out, "parley.schema")
        .iter()
        .map(|l| l["id"].as_str().expect("an id"))
        .collect();
    for id in ["taskalisk.plan", "taskalisk.frontier_node", "parley.error"] {
        assert!(schemas.contains(&id), "{id} in {schemas:?}");
    }
    assert_eq!(out.last().expect("end")["status"], 0);
}

#[test]
fn a_secret_in_the_environment_never_reaches_a_line() {
    let fixture = Fixture::new(
        "(lambda s: (s.update(issues_list_fail_message='bad credentials {GH_TOKEN}'), s)[1])(plan_state())",
    );
    let cwd = fixture.dir.join("secret");
    fs::create_dir_all(&cwd).expect("a directory");
    let output = fixture
        .command(Path::new(env!("CARGO_BIN_EXE_taskalisk")), &cwd)
        .env("GH_TOKEN", "s3cr3t-t0k3n")
        .args(["plan", "--repo", fixture.repo().to_str().expect("UTF-8")])
        .output()
        .expect("the binary runs");
    let run = Run { output, cwd };
    assert_eq!(run.status(), 2, "{}", run.explain());
    let receipt = fs::read_to_string(&run.receipts()[0]).expect("the receipt");
    for text in [
        run.text(),
        String::from_utf8_lossy(&run.output.stderr).into_owned(),
        receipt,
    ] {
        assert!(
            !text.contains("s3cr3t-t0k3n"),
            "a secret reached a line: {text}"
        );
    }
    assert!(String::from_utf8_lossy(&run.output.stderr).contains("[redacted]"));
    let head = &run.receipt()[0];
    assert_eq!(head["redacted"]["env"], json!(["GH_TOKEN"]));
}

/// A token value the gh adapter never sees, so only the writer's redaction
/// can keep it out of a line. Lower case, as a login is normalised.
const TOKEN: &str = "zz9tok0123";

/// The binary with `GH_TOKEN` set to [`TOKEN`], from `cwd`.
fn with_token(fixture: &Fixture, cwd: &Path, args: &[&str]) -> Run {
    fs::create_dir_all(cwd).expect("the working directory");
    let output = fixture
        .command(Path::new(env!("CARGO_BIN_EXE_taskalisk")), cwd)
        .env("GH_TOKEN", TOKEN)
        .args(args)
        .output()
        .expect("the binary runs");
    Run {
        output,
        cwd: cwd.to_owned(),
    }
}

/// No stream, receipt or sidecar of the run holds [`TOKEN`].
fn assert_no_token(run: &Run) {
    let mut texts = vec![
        String::from_utf8_lossy(&run.output.stdout).into_owned(),
        String::from_utf8_lossy(&run.output.stderr).into_owned(),
    ];
    if let Ok(dir) = fs::read_dir(run.cwd.join(".parley/receipts")) {
        for entry in dir {
            let path = entry.expect("an entry").path();
            if path.is_file() {
                texts.push(fs::read_to_string(&path).expect("a receipt"));
            }
        }
    }
    for text in texts {
        assert!(!text.contains(TOKEN), "the token reached a line: {text}");
    }
}

/// The JSON Pointers into `resolved` the receipt head says were redacted.
fn redacted_resolved(run: &Run) -> Vec<Value> {
    run.receipt()[0]["redacted"]["resolved"]
        .as_array()
        .cloned()
        .unwrap_or_default()
}

#[test]
fn a_token_given_as_a_trusted_login_is_redacted_from_the_question() {
    let fixture = Fixture::new("plan_state()");
    let repo = fixture.repo();
    let run = with_token(
        &fixture,
        &fixture.dir.join("trust"),
        &[
            "plan",
            "--repo",
            repo.to_str().expect("UTF-8"),
            "--trust",
            TOKEN,
        ],
    );
    assert_eq!(run.status(), 0, "{}", run.explain());
    assert_no_token(&run);
    let head = &run.receipt()[0];
    assert_eq!(
        head["resolved"]["question"]["trust"]["logins"],
        json!(["[redacted]"])
    );
    assert!(redacted_resolved(&run).contains(&json!("/question/trust/logins/0")));
    assert_valid(&run.receipt());
}

#[test]
fn a_token_inside_a_root_is_redacted_from_the_question_and_the_error() {
    let fixture = Fixture::new("plan_state()");
    let repo = fixture.repo();
    let root = format!("{TOKEN}/elsewhere#1");
    let run = with_token(
        &fixture,
        &fixture.dir.join("root"),
        &[
            "plan",
            "--repo",
            repo.to_str().expect("UTF-8"),
            "--root",
            &root,
        ],
    );
    assert_eq!(run.status(), 2, "{}", run.explain());
    assert_no_token(&run);
    assert!(redacted_resolved(&run).contains(&json!("/question/roots/0")));
    assert_eq!(
        of(&run.stderr(), "parley.error")[0]["code"],
        "root.out_of_scope"
    );
}

#[test]
fn a_token_inside_the_repository_path_is_redacted_from_the_question() {
    let fixture = Fixture::new("plan_state()");
    let repo = fixture.dir.join(format!("repo-{TOKEN}"));
    fs::create_dir_all(&repo).expect("a directory");
    for args in [
        &["init", "-q", "-b", "main"][..],
        &[
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=F",
            "-c",
            "user.email=f@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "base",
        ],
    ] {
        assert!(
            Command::new("git")
                .args(args)
                .current_dir(&repo)
                .status()
                .expect("git")
                .success()
        );
    }
    let run = with_token(
        &fixture,
        &fixture.dir.join("path"),
        &["plan", "--repo", repo.to_str().expect("UTF-8")],
    );
    assert_eq!(run.status(), 0, "{}", run.explain());
    assert_no_token(&run);
    assert!(redacted_resolved(&run).contains(&json!("/question/repo")));
}

#[test]
fn a_token_in_the_working_directory_refuses_the_run() {
    let fixture = Fixture::new("plan_state()");
    let repo = fixture.repo();
    let run = with_token(
        &fixture,
        &fixture.dir.join(format!("cwd-{TOKEN}")),
        &["plan", "--repo", repo.to_str().expect("UTF-8")],
    );
    assert_eq!(run.status(), 3, "{}", run.explain());
    assert!(run.output.stdout.is_empty(), "{}", run.explain());
    let err = run.stderr();
    assert_eq!(err.len(), 1);
    assert_eq!(err[0]["code"], "startup.secret_in_path");
    assert_valid(&err);
    assert_no_token(&run);
    assert_eq!(run.receipts().len(), 0, "no receipt");
}

#[test]
fn a_parley_directory_git_would_stage_refuses_the_run() {
    let fixture = Fixture::new("plan_state()");
    let repo = fixture.repo();
    for (n, gitignore) in ["receipts/old.jsonl\n", "*\n!receipts/\n", ""]
        .iter()
        .enumerate()
    {
        let cwd = fixture.dir.join(format!("stageable-{n}"));
        fs::create_dir_all(cwd.join(".parley")).expect("a directory");
        fs::write(cwd.join(".parley/.gitignore"), gitignore).expect("a .gitignore");
        let run = fixture.run_in(
            &format!("stageable-{n}"),
            &["plan", "--repo", repo.to_str().expect("UTF-8")],
        );
        assert_eq!(run.status(), 3, "{gitignore:?}: {}", run.explain());
        let err = run.stderr();
        assert_eq!(err[0]["code"], "startup.receipt_stageable", "{gitignore:?}");
        assert_valid(&err);
        assert_eq!(run.receipts().len(), 0, "{gitignore:?}: no receipt");
        assert_eq!(
            fs::read_to_string(cwd.join(".parley/.gitignore")).expect("kept"),
            *gitignore,
            "a user's file is left alone"
        );
    }
}

#[test]
fn a_closed_output_ends_the_run_with_4() {
    let fixture = Fixture::new("plan_state()");
    let cwd = fixture.dir.join("closed");
    fs::create_dir_all(&cwd).expect("a directory");
    let mut child = fixture
        .command(Path::new(env!("CARGO_BIN_EXE_taskalisk")), &cwd)
        .args(["plan", "--repo", fixture.repo().to_str().expect("UTF-8")])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("the binary runs");
    drop(child.stdout.take());
    let output = child.wait_with_output().expect("it ends");
    let run = Run { output, cwd };
    assert_eq!(run.status(), 4, "{}", run.explain());
    let receipt = parse(&fs::read(&run.receipts()[0]).expect("the receipt"));
    assert_eq!(receipt.last().expect("end")["status"], 4);
}

#[test]
fn a_gitignore_is_judged_as_the_python_writer_judges_it() {
    let fixture = Fixture::new("plan_state()");
    let repo = fixture.repo();
    for (n, (gitignore, status)) in [("*\n!.gitignore\n", 0), ("*\nfoo\0bar\n", 3)]
        .iter()
        .enumerate()
    {
        let cwd = fixture.dir.join(format!("judged-{n}"));
        fs::create_dir_all(cwd.join(".parley")).expect("a directory");
        fs::write(cwd.join(".parley/.gitignore"), gitignore).expect("a .gitignore");
        let run = fixture.run_in(
            &format!("judged-{n}"),
            &["plan", "--repo", repo.to_str().expect("UTF-8")],
        );
        assert_eq!(run.status(), *status, "{gitignore:?}: {}", run.explain());
    }
}

/// #51: a reference gh cannot find ends the run with `issue.not_found`,
/// naming the reference and the part not found, by lookups of the owner and
/// the repository; every line validates against its schema.
#[test]
fn a_reference_gh_cannot_find_is_issue_not_found_with_the_reference() {
    for (args, reference, not_found, rule) in [
        (
            &["--trust-owner", "nobody", "--root", "nobody/x#1"][..],
            "nobody/x#1",
            "owner",
            "D11",
        ),
        (
            &["--root", "flyingrobots/nothere#1"][..],
            "flyingrobots/nothere#1",
            "repository",
            "D12",
        ),
        (
            &["--root", "flyingrobots/geordi#404"][..],
            "flyingrobots/geordi#404",
            "number",
            "D13",
        ),
    ] {
        let fixture = Fixture::new("plan_state()");
        let run = fixture.plan(args);
        assert_eq!(run.status(), 2, "{}", run.explain());
        let (out, err) = (run.stdout(), run.stderr());
        assert_valid(&out);
        assert_valid(&err);
        assert_valid(&run.receipt());
        assert!(of(&out, "taskalisk.plan").is_empty(), "{}", run.explain());
        let errors = of(&err, "parley.error");
        assert_eq!(errors.len(), 1, "{}", run.explain());
        assert_eq!(errors[0]["code"], "issue.not_found", "{}", run.explain());
        assert_eq!(errors[0]["detail"]["reference"], reference);
        assert_eq!(errors[0]["detail"]["not_found"], not_found);
        assert_eq!(errors[0]["detail"]["rule"], rule);
        assert_eq!(errors[0]["detail"]["source"], "gh");
        let message = errors[0]["problem"].as_str().expect("a problem");
        assert_eq!(
            message.contains("private repository"),
            not_found == "repository",
            "{message}"
        );
    }
}
