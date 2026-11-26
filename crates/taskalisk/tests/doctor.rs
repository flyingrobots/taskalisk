//! `taskalisk doctor --bundle FILE` (flyingrobots/taskalisk#49): every
//! finding of a recorded observation bundle, grouped by issue, with reads
//! disabled, and an exit status that follows the worst finding.
//!
//! Each finding family has a bundle built here: document findings, the
//! profile's run findings, body warnings, shape warnings, plan warnings,
//! trust warnings, and the cause of an incomplete run (D11 to D13).
//!
//! "Reads disabled" is proven, not assumed: every run has a `gh` and a `git`
//! first on `PATH` that log each call and fail, and both logs stay empty.
#![cfg(unix)]

use std::collections::BTreeSet;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};

use serde_json::{Map, Value, json};

static NEXT: AtomicUsize = AtomicUsize::new(0);

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("the repository root")
}

/// A temporary directory with a `bin/` whose `gh` and `git` log every call
/// and fail.
struct Fixture {
    dir: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let dir = std::env::temp_dir().join(format!(
            "taskalisk-doctor-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("bin")).expect("a temporary directory");
        let dir = dir.canonicalize().expect("a canonical directory");
        for tool in ["gh", "git"] {
            let path = dir.join("bin").join(tool);
            fs::write(
                &path,
                format!(
                    "#!/bin/sh\necho \"{tool} $*\" >> '{}'\nexit 1\n",
                    dir.join("reads.log").display()
                ),
            )
            .expect("a script");
            fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).expect("executable");
        }
        fs::write(dir.join("reads.log"), "").expect("the log");
        Self { dir }
    }

    /// Writes `bundle` as `name` and returns its path.
    fn bundle(&self, name: &str, bundle: &Value) -> String {
        let path = self.dir.join(name);
        fs::write(&path, serde_json::to_string_pretty(bundle).expect("JSON")).expect("a bundle");
        path.to_str().expect("UTF-8").to_owned()
    }

    /// The binary, run from `cwd` under the fixture, with the logging `gh`
    /// and `git` first on `PATH`.
    fn run(&self, cwd: &str, args: &[&str]) -> Run {
        let cwd = self.dir.join(cwd);
        fs::create_dir_all(&cwd).expect("the working directory");
        let mut path = self.dir.join("bin").into_os_string();
        path.push(":");
        path.push(std::env::var_os("PATH").unwrap_or_default());
        let mut command = Command::new(env!("CARGO_BIN_EXE_taskalisk"));
        command
            .current_dir(&cwd)
            .env("PATH", path)
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
        Run {
            output: command.output().expect("the binary runs"),
        }
    }

    /// `doctor --bundle FILE` with `extra` flags.
    fn doctor(&self, file: &str, extra: &[&str]) -> Run {
        let mut args = vec!["doctor", "--bundle", file];
        args.extend_from_slice(extra);
        self.run("work", &args)
    }

    /// What `gh` and `git` were asked, which must be nothing.
    fn reads(&self) -> String {
        fs::read_to_string(self.dir.join("reads.log")).expect("the log")
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

impl Run {
    fn status(&self) -> i32 {
        self.output.status.code().expect("an exit status")
    }

    fn text(&self) -> String {
        String::from_utf8(self.output.stdout.clone()).expect("UTF-8")
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
            .filter(|l| schema(l) == "parley.error")
            .collect()
    }

    /// The summary line.
    fn summary(&self) -> Value {
        self.stdout()
            .into_iter()
            .find(|l| schema(l) == "taskalisk.doctor")
            .unwrap_or_else(|| panic!("no summary line: {}", self.explain()))
    }

    /// The group lines, in order.
    fn groups(&self) -> Vec<Value> {
        self.stdout()
            .into_iter()
            .filter(|l| schema(l) == "taskalisk.doctor.issue")
            .collect()
    }

    /// Every finding as `subject code`, in output order.
    fn findings(&self) -> Vec<String> {
        self.groups()
            .iter()
            .flat_map(|g| {
                let subject = g["subject"].as_str().unwrap_or("(plan)").to_owned();
                g["findings"]
                    .as_array()
                    .expect("findings")
                    .iter()
                    .map(move |f| format!("{subject} {}", f["code"].as_str().expect("a code")))
                    .collect::<Vec<_>>()
            })
            .collect()
    }

    /// Every line of stdout, stderr and the receipt validates against the
    /// exact schema it names.
    fn validate(&self) {
        let mut lines = self.stdout();
        lines.extend(self.stderr());
        lines.extend(self.receipt());
        validate(&lines);
    }
}

fn parse(bytes: &[u8]) -> Vec<Value> {
    std::str::from_utf8(bytes)
        .expect("UTF-8")
        .lines()
        .map(|line| serde_json::from_str(line).unwrap_or_else(|e| panic!("not JSON ({e}): {line}")))
        .collect()
}

fn schema(line: &Value) -> &str {
    line["_schema"]["id"].as_str().unwrap_or_default()
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

// ---- Bundles ---------------------------------------------------------------

/// The sections every canonical template opens with, so a task body draws
/// no body warning.
const SECTIONS: &str = "\n## Outcome\n\nThe thing works.\n\n## Scope\n\n- The thing.\n\n## Acceptance\n\n- [ ] It works.\n";

/// A frontmatter document at `id` with the entry `lines`, then `rest`.
fn document(id: &str, lines: &str, rest: &str) -> String {
    format!("```yaml\n.dag: issue-dag/2\n.id: {id}\n{lines}```\n{rest}")
}

/// A well-written task of two hours at `id`, blocked by `blocked_by`.
fn task(id: &str, blocked_by: &str) -> String {
    document(
        id,
        &format!(".kind: task\n.type: feature\n.blocked_by: [{blocked_by}]\n.size_hours: 2\n"),
        SECTIONS,
    )
}

/// An open issue at `address` by the owner `o`, holding `text`, edited by
/// `editors` after its author.
fn issue(address: &str, text: &str, editors: &[&str]) -> (String, Value) {
    let editors: Vec<Value> = std::iter::once("o")
        .chain(editors.iter().copied())
        .map(|login| json!({"login": login, "type": "User"}))
        .collect();
    (
        address.to_owned(),
        json!({"value": {
            "address": address,
            "author": {"login": "o", "type": "User"},
            "author_association": "OWNER",
            "body": {"value": {"editors": editors, "text": text}},
            "pull_request": false,
            "state": "open",
            "state_reason": null,
        }}),
    )
}

/// A bundle of `o/r` with `roots`, `issues`, and the permissions `logins`
/// hold in `o/r` (`null` for none).
fn bundle(roots: &[&str], issues: Vec<(String, Value)>, logins: &[(&str, Value)]) -> Value {
    let mut permissions = Map::new();
    permissions.insert("o".to_owned(), json!({"value": null}));
    for (login, permission) in logins {
        permissions.insert((*login).to_owned(), json!({ "value": permission }));
    }
    json!({
        "bundle": "issue-dag-observations/1",
        "format": "issue-dag/2",
        "profile": "issue-dag-planning/2",
        "observations": {
            "home_open_pull_requests": {"value": []},
            "issues": issues.into_iter().collect::<Map<String, Value>>(),
            "permissions": {"o/r": permissions},
        },
        "parameters": {
            "capacities": {},
            "home": "o/r",
            "read_scope": {"owners": ["o"], "repositories": []},
            "roots": roots,
            "trust": {"codeowners": false, "logins": ["dev"], "policy": "taskalisk/threat-model"},
        },
    })
}

/// One well-written task: no finding at all.
fn clean() -> Value {
    bundle(
        &["o/r#1"],
        vec![issue("o/r#1", &task("o/r#1", ""), &[])],
        &[],
    )
}

/// One task with no estimate: one warning (`taskalisk.estimate-missing`).
fn one_warning() -> Value {
    let text = document(
        "o/r#1",
        ".kind: task\n.type: feature\n.blocked_by: []\n",
        SECTIONS,
    );
    bundle(&["o/r#1"], vec![issue("o/r#1", &text, &[])], &[])
}

/// One task with one error (`profile.X1`: a copied `.id`) and one warning
/// (`taskalisk.estimate-missing`). A single task keeps the graph's own
/// warnings (isolation, density) out.
fn one_error_one_warning() -> Value {
    let text = document(
        "o/r#7",
        ".kind: task\n.type: feature\n.blocked_by: []\n",
        SECTIONS,
    );
    bundle(&["o/r#1"], vec![issue("o/r#1", &text, &[])], &[])
}

/// Document findings: a task over eight hours (`format.V10`), and a
/// prerequisite whose document has an unknown format key (`format.V2`).
fn documents() -> Value {
    let large = document(
        "o/r#1",
        ".kind: task\n.type: feature\n.blocked_by: [o/r#2]\n.size_hours: 9\n",
        SECTIONS,
    );
    let unknown_key = document(
        "o/r#2",
        ".kind: task\n.type: feature\n.blocked_by: []\n.size_hours: 2\n.colour: red\n",
        SECTIONS,
    );
    bundle(
        &["o/r#1"],
        vec![
            issue("o/r#1", &large, &[]),
            issue("o/r#2", &unknown_key, &[]),
        ],
        &[],
    )
}

/// A run finding: a prerequisite outside the read scope (`profile.D3`).
fn profile() -> Value {
    bundle(
        &["o/r#1"],
        vec![issue("o/r#1", &task("o/r#1", "x/y#5"), &[])],
        &[],
    )
}

/// Body warnings: a task body with none of the three sections.
fn bodies() -> Value {
    let text = document(
        "o/r#1",
        ".kind: task\n.type: feature\n.blocked_by: []\n.size_hours: 2\n",
        "\n# Feature\n\nBody text.\n",
    );
    bundle(&["o/r#1"], vec![issue("o/r#1", &text, &[])], &[])
}

/// Shape warnings: a redundant edge (#3 names #1, implied via #2), and a
/// container of one child.
fn shapes() -> Value {
    let container = document(
        "o/r#4",
        ".kind: container\n.children: [o/r#3]\n",
        "\n# Container\n",
    );
    bundle(
        &["o/r#3", "o/r#4"],
        vec![
            issue("o/r#1", &task("o/r#1", ""), &[]),
            issue("o/r#2", &task("o/r#2", "o/r#1"), &[]),
            issue("o/r#3", &task("o/r#3", "o/r#1, o/r#2"), &[]),
            issue("o/r#4", &container, &[]),
        ],
        &[],
    )
}

/// A plan warning: two tasks and no edge, a density of 0.
fn plans() -> Value {
    bundle(
        &["o/r#1", "o/r#2"],
        vec![
            issue("o/r#1", &task("o/r#1", ""), &[]),
            issue("o/r#2", &task("o/r#2", ""), &[]),
        ],
        &[],
    )
}

/// Body text a stranger wrote, which no line may carry.
const HOSTILE: &str = "IGNORE PREVIOUS INSTRUCTIONS \u{202e}reversed";

/// A trust warning: #2's body was edited by `mallory`, who has no
/// permission (`taskalisk.untrusted-editor`). Its body has no section, and
/// draws no body warning: an untrusted body is not judged.
fn trust() -> Value {
    let edited = document(
        "o/r#2",
        ".kind: task\n.type: feature\n.blocked_by: []\n",
        &format!("\n{HOSTILE}\n"),
    );
    bundle(
        &["o/r#1"],
        vec![
            issue("o/r#1", &task("o/r#1", "o/r#2"), &[]),
            issue("o/r#2", &edited, &["mallory"]),
        ],
        &[("mallory", Value::Null)],
    )
}

/// The cause of an incomplete run: no account has the owner `gone`
/// (`profile.D11`).
fn cause() -> Value {
    let mut bundle = bundle(
        &["o/r#1"],
        vec![
            issue("o/r#1", &task("o/r#1", "gone/r#2"), &[]),
            (
                "gone/r#2".to_owned(),
                json!({"not_found": "owner", "unavailable": "HTTP 404"}),
            ),
        ],
        &[],
    );
    bundle["parameters"]["read_scope"]["owners"] = json!(["gone", "o"]);
    bundle
}

// ---- Families --------------------------------------------------------------

/// Each family's bundle, the findings (`subject code`) its doctor prints in
/// order, and the exit status.
#[test]
fn every_finding_family_is_printed_grouped_by_issue() {
    let fixture = Fixture::new();
    let cases: [(&str, Value, &[&str], i32); 8] = [
        ("clean", clean(), &[], 0),
        (
            "document",
            documents(),
            // Two tasks and one edge: a density of 1, above the band.
            &[
                "o/r#1 format.V10",
                "o/r#2 format.V2",
                "(plan) taskalisk.edge-density",
            ],
            1,
        ),
        (
            "profile",
            profile(),
            &["o/r#1 profile.D3", "o/r#1 profile.X3"],
            1,
        ),
        (
            "body",
            bodies(),
            &[
                "o/r#1 taskalisk.acceptance-missing",
                "o/r#1 taskalisk.outcome-missing",
                "o/r#1 taskalisk.scope-missing",
            ],
            0,
        ),
        (
            "shape",
            shapes(),
            &[
                "o/r#3 taskalisk.redundant-edge",
                "o/r#4 taskalisk.small-container",
                "(plan) taskalisk.edge-density",
            ],
            0,
        ),
        (
            "plan",
            plans(),
            &[
                "o/r#1 taskalisk.isolated-task",
                "o/r#2 taskalisk.isolated-task",
                "(plan) taskalisk.edge-density",
            ],
            0,
        ),
        (
            "trust",
            trust(),
            // #2 stays in the graph as an opaque blocker: one edge, two
            // nodes, a density of 1.
            &[
                "o/r#2 taskalisk.untrusted-editor",
                "(plan) taskalisk.edge-density",
            ],
            0,
        ),
        ("cause", cause(), &["gone/r#2 profile.D11"], 1),
    ];
    for (name, bundle, expected, status) in cases {
        let file = fixture.bundle(&format!("{name}.json"), &bundle);
        let run = fixture.doctor(&file, &[]);
        assert_eq!(run.status(), status, "{name}: {}", run.explain());
        assert_eq!(run.findings(), expected, "{name}: {}", run.explain());
        assert!(run.errors().is_empty(), "{name}: {}", run.explain());
        run.validate();
        let summary = run.summary();
        let errors = expected
            .iter()
            .filter(|f| f.contains(" format.V2") || f.contains(" profile."))
            .count();
        assert_eq!(summary["errors"], errors, "{name}: {}", run.explain());
        assert_eq!(
            summary["warnings"],
            expected.len() - errors,
            "{name}: {}",
            run.explain()
        );
        assert_eq!(summary["ok"], errors == 0, "{name}: {}", run.explain());
    }
    assert_eq!(fixture.reads(), "", "the doctor read gh or git");
}

#[test]
fn a_group_is_one_issue_and_carries_each_findings_severity_and_detail() {
    let fixture = Fixture::new();
    let run = fixture.doctor(&fixture.bundle("shape.json", &shapes()), &[]);
    let groups = run.groups();
    let subjects: Vec<&Value> = groups.iter().map(|g| &g["subject"]).collect();
    assert_eq!(
        subjects,
        [&json!("o/r#3"), &json!("o/r#4"), &Value::Null],
        "{}",
        run.explain()
    );
    let redundant = &groups[0]["findings"][0];
    assert_eq!(redundant["severity"], "warning");
    assert_eq!(redundant["family"], "shape");
    assert_eq!(redundant["concerns"], "o/r#1");
    assert_eq!(redundant["detail"]["implied_via"], "o/r#2");
    let density = &groups[2]["findings"][0];
    assert_eq!(density["family"], "plan");
    assert_eq!(density["detail"]["density"], 0.6667);
    assert_eq!(density["detail"]["band"], json!([0.01, 0.5]));

    let run = fixture.doctor(&fixture.bundle("trust.json", &trust()), &[]);
    let editor = &run.groups()[0]["findings"][0];
    assert_eq!(editor["family"], "trust");
    assert_eq!(editor["detail"]["login"], "mallory");
    assert!(editor["detail"]["rule"].is_string(), "{}", run.explain());
    assert!(
        !run.text().contains("IGNORE") && !run.text().contains('\u{202e}'),
        "an untrusted body reached a line: {}",
        run.explain()
    );

    let run = fixture.doctor(&fixture.bundle("cause.json", &cause()), &[]);
    let cause = &run.groups()[0]["findings"][0];
    assert_eq!(cause["severity"], "error");
    assert_eq!(cause["family"], "cause");
    assert_eq!(cause["detail"]["rule"], "D11");
    assert_eq!(cause["detail"]["not_found"], "owner");
}

// ---- Exit statuses ---------------------------------------------------------

#[test]
fn an_error_exits_1_and_a_warning_only_under_strict() {
    let fixture = Fixture::new();
    let both = fixture.bundle("both.json", &one_error_one_warning());
    let run = fixture.doctor(&both, &[]);
    assert_eq!(run.status(), 1, "{}", run.explain());
    assert_eq!(
        run.findings(),
        ["o/r#1 profile.X1", "o/r#1 taskalisk.estimate-missing"],
        "{}",
        run.explain()
    );
    assert_eq!(run.summary()["ok"], false);
    run.validate();

    let warning = fixture.bundle("warning.json", &one_warning());
    let run = fixture.doctor(&warning, &[]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    assert_eq!(run.findings(), ["o/r#1 taskalisk.estimate-missing"]);
    assert_eq!(run.summary()["strict"], false);
    assert_eq!(run.summary()["ok"], true);
    let run = fixture.doctor(&warning, &["--strict"]);
    assert_eq!(run.status(), 1, "{}", run.explain());
    assert_eq!(run.summary()["strict"], true);
    assert_eq!(run.summary()["ok"], false);
    run.validate();

    let run = fixture.doctor(&fixture.bundle("clean.json", &clean()), &["--strict"]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    assert!(run.groups().is_empty(), "{}", run.explain());
    // The end line states the status the process exits with.
    let warned = fixture.doctor(&warning, &["--strict"]);
    let end = warned.stdout().pop().expect("an end line");
    assert_eq!(end["status"], 1, "{}", warned.explain());
    assert_eq!(fixture.reads(), "");
}

#[test]
fn a_bundle_that_cannot_be_read_exits_2_and_prints_no_finding() {
    let fixture = Fixture::new();
    let absent = fixture.dir.join("absent.json");
    let not_json = fixture.dir.join("not-json.json");
    fs::write(&not_json, "{ not json").expect("a file");
    let not_bundle = fixture.dir.join("not-a-bundle.json");
    fs::write(&not_bundle, r#"{"bundle": "issue-dag-observations/9"}"#).expect("a file");
    let mut incomplete = clean();
    incomplete["observations"]
        .as_object_mut()
        .expect("observations")
        .remove("home_open_pull_requests");
    let incomplete = fixture.bundle("incomplete.json", &incomplete);
    for (file, code) in [
        (absent.to_str().expect("UTF-8"), "bundle.unreadable"),
        (not_json.to_str().expect("UTF-8"), "bundle.invalid"),
        (not_bundle.to_str().expect("UTF-8"), "bundle.invalid"),
        (incomplete.as_str(), "bundle.incomplete"),
    ] {
        for strict in [&[][..], &["--strict"]] {
            let run = fixture.doctor(file, strict);
            assert_eq!(run.status(), 2, "{file}: {}", run.explain());
            assert_eq!(run.errors()[0]["code"], code, "{file}: {}", run.explain());
            assert!(
                run.stdout()
                    .iter()
                    .all(|l| !schema(l).starts_with("taskalisk.")),
                "{file}: a finding was printed: {}",
                run.explain()
            );
            run.validate();
        }
    }
    assert_eq!(fixture.reads(), "");
}

// ---- Output ----------------------------------------------------------------

/// A run's lines without what differs between runs: the envelope's time
/// and run id, and the receipt path.
fn stable(run: &Run) -> String {
    run.stdout()
        .into_iter()
        .map(|mut l| {
            let object = l.as_object_mut().expect("an object");
            for key in ["t", "run", "paths", "receipt"] {
                object.remove(key);
            }
            l.to_string() + "\n"
        })
        .collect()
}

#[test]
fn the_json_output_is_identical_across_runs_and_json_is_the_default() {
    let fixture = Fixture::new();
    let file = fixture.bundle("shape.json", &shapes());
    let first = fixture.doctor(&file, &["--json"]);
    let second = fixture.doctor(&file, &["--json"]);
    let default = fixture.doctor(&file, &[]);
    assert_eq!(stable(&first), stable(&second));
    assert_eq!(stable(&first), stable(&default));
    // Only the envelope differs: the result lines are byte for byte equal
    // once it is removed.
    assert!(stable(&first).contains("taskalisk.doctor.issue"));
}

#[test]
fn the_receipt_declares_the_bundle_as_input_and_no_network() {
    let fixture = Fixture::new();
    let file = fixture.bundle("plan.json", &plans());
    let run = fixture.doctor(&file, &[]);
    let receipt = run.receipt();
    let head = receipt
        .iter()
        .find(|l| l["event"] == "receipt.head")
        .expect("a head");
    assert_eq!(head["argv"][1], "doctor");
    assert_eq!(head["effects"]["network"], false);
    assert_eq!(head["effects"]["writes"], json!([]));
    assert_eq!(head["inputs"][0]["role"], "observations");
    let inputs = receipt
        .iter()
        .find(|l| l["event"] == "receipt.inputs")
        .expect("the inputs");
    assert!(inputs["inputs"][0]["sha256"].is_string(), "{inputs}");
    assert_eq!(fixture.reads(), "");
}

#[test]
fn human_output_is_grouped_by_issue_and_escapes_github_text() {
    let fixture = Fixture::new();
    // A login a planted bundle could carry: a line break and an override.
    let mut planted = trust();
    let edited = &mut planted["observations"]["issues"]["o/r#2"]["value"]["body"]["value"];
    edited["editors"][1]["login"] = json!("mal\nlory\u{202e}");
    planted["observations"]["permissions"]["o/r"]["mal\nlory\u{202e}"] = json!({"value": null});
    let file = fixture.bundle("planted.json", &planted);
    // The bundle loader takes a login as recorded, so it reaches a trust
    // warning's detail, and --human must escape it.
    let json_run = fixture.doctor(&file, &[]);
    assert_eq!(json_run.status(), 0, "{}", json_run.explain());
    json_run.validate();
    let human = fixture.doctor(&file, &["--human"]);
    let text = human.text();
    assert!(!text.contains('\u{202e}'), "{text}");
    assert!(text.contains("login=mal\\u000alory\\u202e"), "{text}");
    let human = fixture.doctor(&fixture.bundle("shape.json", &shapes()), &["--human"]);
    assert_eq!(human.status(), 0, "{}", human.explain());
    let text = human.text();
    let lines: Vec<&str> = text.lines().collect();
    let at = |needle: &str| {
        lines
            .iter()
            .position(|l| l.starts_with(needle))
            .unwrap_or_else(|| panic!("no line {needle:?}: {text}"))
    };
    let (three, four, plan) = (at("o/r#3"), at("o/r#4"), at("the plan"));
    assert!(three < four && four < plan, "{text}");
    assert!(
        lines[three + 1]
            .trim_start()
            .starts_with("warning taskalisk.redundant-edge"),
        "{text}"
    );
    assert!(
        lines[four + 1]
            .trim_start()
            .starts_with("warning taskalisk.small-container"),
        "{text}"
    );
    assert!(
        text.lines()
            .next()
            .expect("a line")
            .contains("3 warning(s)"),
        "{text}"
    );
    for line in &lines {
        assert!(!line.starts_with('{'), "a JSON line under --human: {text}");
    }
}

// ---- Arguments -------------------------------------------------------------

#[test]
fn doctor_refuses_arguments_it_cannot_honour() {
    let fixture = Fixture::new();
    for args in [
        &["doctor"][..],
        &["doctor", "--bundle"],
        &["doctor", "--bundle", "a.json", "--bundle", "b.json"],
        &["doctor", "--bundle", "a.json", "--json", "--human"],
        &["doctor", "--bundle", "a.json", "--from-github"],
        &["doctor", "--bundle", "a.json", "--repo", "."],
        &["doctor", "--bundle", "a.json", "--strict=yes"],
        &["doctor", "--bundle", "a.json", "extra"],
    ] {
        let run = fixture.run("work", args);
        assert_eq!(run.status(), 3, "{args:?}: {}", run.explain());
        // With --human the one line is prose; it names the code either way.
        assert!(
            String::from_utf8_lossy(&run.output.stderr).contains("startup.arguments_invalid"),
            "{args:?}: {}",
            run.explain()
        );
        assert!(run.output.stdout.is_empty(), "{args:?}: {}", run.explain());
    }
    let file = fixture.bundle("clean.json", &clean());
    let run = fixture.run("work", &["doctor", &format!("--bundle={file}")]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    assert_eq!(fixture.reads(), "");
}

#[test]
fn doctor_help_describes_the_command_and_its_schemas() {
    let fixture = Fixture::new();
    let run = fixture.run("work", &["doctor", "--help"]);
    assert_eq!(run.status(), 0, "{}", run.explain());
    let lines = run.stdout();
    let command = lines
        .iter()
        .find(|l| l["event"] == "command")
        .expect("a command line");
    assert_eq!(command["name"], "doctor");
    assert_eq!(command["effects"]["network"], false);
    let described: BTreeSet<&str> = lines
        .iter()
        .filter(|l| l["event"] == "schema")
        .filter_map(|l| l["id"].as_str())
        .collect();
    for id in [
        "taskalisk.doctor",
        "taskalisk.doctor.issue",
        "parley.error",
        "parley.startup.failed",
    ] {
        assert!(described.contains(id), "{id}: {}", run.explain());
    }
    run.validate();
}
