//! The renderer against the Python compiler, on the graph cases of the
//! vendored corpus where the Python and the specification agree.
//!
//! `tests/fixtures/render/python/<case>.jsonl` holds the result lines the
//! Python writes for a case (captured by `tests/capture_render_parity.py`,
//! kept current by `tests/test_render_parity.py`). For each, the case's
//! bundle is planned by `issue-dag-core` and rendered, and:
//!
//! - the rendering equals the recorded Rust rendering,
//!   `tests/fixtures/render/rust/<case>.jsonl`, byte for byte, and two
//!   renderings are identical (`TASKALISK_BLESS=1` rewrites the recording);
//! - every line equals the Python's line once the fields in [`gaps`] are
//!   removed from it: exactly those, no more and no fewer. A field in the
//!   list is one the core's result does not hold (see the `render` module).
//!
//! `frontmatter.violation` and `frontmatter.warning` compare as the set of
//! their subjects: the Python writes one line per message, with the value
//! in the message, and the core one per rule, with fixed text.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use issue_dag_bundle::load;
use issue_dag_core::{RecordedForge, plan};
use serde_json::Value;
use taskalisk::render::render;

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn fixtures() -> PathBuf {
    root().join("tests/fixtures/render")
}

fn bundle_text(case: &str) -> String {
    let path = root()
        .join("tests/fixtures/issue-dag/corpus/cases/graph")
        .join(case)
        .join("bundle.json");
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

fn rendered(case: &str) -> Result<String, String> {
    let bundle = load(&bundle_text(case)).map_err(|e| format!("bundle rejected: {e}"))?;
    let forge = RecordedForge::new(&bundle.observations);
    let outcome = plan(&bundle.parameters, &forge).map_err(|e| e.to_string())?;
    render(&bundle.parameters, &outcome).map_err(|e| format!("not rendered: {e:?}"))
}

fn lines(text: &str) -> Vec<Value> {
    text.lines()
        .map(|l| serde_json::from_str(l).unwrap_or_else(|e| panic!("{e}: {l}")))
        .collect()
}

fn cases() -> Vec<String> {
    let mut names: Vec<String> = fs::read_dir(fixtures().join("python"))
        .expect("the Python fixtures are present")
        .filter_map(|e| {
            let name = e.expect("entry").file_name().into_string().expect("UTF-8");
            name.strip_suffix(".jsonl").map(str::to_owned)
        })
        .collect();
    names.sort();
    names
}

/// The fields of a Python line the renderer does not write, as paths from
/// the line; `*` stands for every item of a list.
fn gaps(line: &Value) -> Vec<&'static str> {
    const NODE: [&str; 7] = [
        "title",
        "url",
        "type",
        "workstream",
        "size_hours",
        "linked_open_prs",
        "recoverable_branches",
    ];
    let codeowners = line
        .pointer("/source/trust/codeowners")
        .is_some_and(|c| !c.is_null());
    match line["event"].as_str() {
        Some("plan") if codeowners => vec![
            "artifact_hash",
            "source/trust/codeowners",
            "source/trust/codeowners_teams_not_expanded",
        ],
        Some("plan") => vec!["artifact_hash"],
        Some("frontier_node" | "node") => NODE.to_vec(),
        Some("batch") => vec!["members/*/title", "members/*/url", "members/*/workstream"],
        Some("finding") => match line["code"].as_str() {
            Some("container.excluded" | "issue.opaque" | "parent.not_planned") => {
                vec!["detail/title"]
            }
            Some("issue.unmodeled") => vec!["detail/title", "detail/url"],
            Some("issue.untrusted") => vec![
                "message",
                "detail/url",
                "detail/state",
                "detail/author",
                "detail/reasons",
                "detail/referenced_by",
            ],
            Some("pull_request.untrusted") => vec![
                "message",
                "detail/url",
                "detail/author",
                "detail/cross_repository",
                "detail/closes",
                "detail/reason",
            ],
            Some("frontmatter.violation" | "frontmatter.warning") => vec!["message"],
            _ => Vec::new(),
        },
        _ => Vec::new(),
    }
}

/// Removes one path from a value; whether anything was there.
fn remove(value: &mut Value, path: &[&str]) -> bool {
    match path {
        [] => false,
        ["*", rest @ ..] => value
            .as_array_mut()
            .is_some_and(|items| items.iter_mut().fold(true, |all, i| remove(i, rest) && all)),
        [key] => value
            .as_object_mut()
            .is_some_and(|o| o.remove(*key).is_some()),
        [key, rest @ ..] => value.get_mut(*key).is_some_and(|v| remove(v, rest)),
    }
}

/// The Python line without its gaps; a gap the line lacks is a problem.
fn stripped(line: &Value, problems: &mut Vec<String>) -> Value {
    let mut out = line.clone();
    for gap in gaps(line) {
        let path: Vec<&str> = gap.split('/').collect();
        if !remove(&mut out, &path) {
            problems.push(format!("the Python line has no {gap}: {line}"));
        }
    }
    out
}

/// The lines in the form they compare in: every line but the
/// `frontmatter.*` findings in order, and those as a set of (code, subject).
fn comparable(lines: Vec<Value>) -> (Vec<Value>, BTreeSet<(String, String)>) {
    let mut ordered = Vec::new();
    let mut frontmatter = BTreeSet::new();
    for line in lines {
        match line["code"].as_str() {
            Some(code) if line["event"] == "finding" && code.starts_with("frontmatter.") => {
                let subject = line["subject"].as_str().unwrap_or_default().to_owned();
                frontmatter.insert((code.to_owned(), subject));
            }
            _ => ordered.push(line),
        }
    }
    (ordered, frontmatter)
}

#[test]
fn every_agreed_case_renders_as_the_python_does() {
    let bless = std::env::var_os("TASKALISK_BLESS").is_some();
    let names = cases();
    assert!(names.len() > 100, "too few cases: {}", names.len());
    let mut failures = Vec::new();
    for case in &names {
        let text = match rendered(case) {
            Ok(text) => text,
            Err(why) => {
                failures.push(format!("{case}: {why}"));
                continue;
            }
        };
        let mut problems = Vec::new();
        if rendered(case).as_deref() != Ok(text.as_str()) {
            problems.push("two renderings differ".to_owned());
        }
        let recorded = fixtures().join("rust").join(format!("{case}.jsonl"));
        if bless {
            fs::create_dir_all(recorded.parent().expect("parent")).expect("mkdir");
            fs::write(&recorded, &text).expect("write the recording");
        } else if fs::read_to_string(&recorded).ok().as_deref() != Some(text.as_str()) {
            problems.push(format!(
                "differs from {} (TASKALISK_BLESS=1 rewrites it)",
                recorded.display()
            ));
        }
        let python_text =
            fs::read_to_string(fixtures().join("python").join(format!("{case}.jsonl")))
                .expect("the Python fixture");
        let want = comparable(
            lines(&python_text)
                .iter()
                .map(|l| stripped(l, &mut problems))
                .collect(),
        );
        let ((want, want_frontmatter), (got, got_frontmatter)) = (want, comparable(lines(&text)));
        if want_frontmatter != got_frontmatter {
            problems.push(format!(
                "frontmatter findings: python {want_frontmatter:?}, rust {got_frontmatter:?}"
            ));
        }
        if want.len() != got.len() {
            problems.push(format!("{} lines, the Python {}", got.len(), want.len()));
        }
        for (n, (w, g)) in want.iter().zip(&got).enumerate() {
            if w != g {
                problems.push(format!("line {}:\n  python {w}\n  rust   {g}", n + 1));
            }
        }
        if !problems.is_empty() {
            failures.push(format!("{case}:\n {}", problems.join("\n ")));
        }
    }
    assert!(
        failures.is_empty(),
        "{} of {} cases differ:\n{}",
        failures.len(),
        names.len(),
        failures.join("\n")
    );
}
