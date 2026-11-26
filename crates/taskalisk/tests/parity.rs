//! The renderer against the Python compiler, on the graph cases of the
//! vendored corpus where the Python and the specification agree.
//!
//! `tests/fixtures/render/python/<case>.jsonl` holds the result lines the
//! Python writes for a case (captured by `tests/capture_render_parity.py`,
//! kept current by `tests/test_render_parity.py`). For each, the case's
//! bundle is planned by `issue-dag-core` and rendered with a display input
//! read from those lines (titles, URLs, branches, CODEOWNERS persons and
//! teams: what the adapters will supply, flyingrobots/taskalisk#31), and:
//!
//! - the rendering equals the recorded Rust rendering,
//!   `tests/fixtures/render/rust/<case>.jsonl`, byte for byte, and two
//!   renderings are identical (`TASKALISK_BLESS=1` rewrites the recording);
//! - every line equals the Python's line once the fields in [`gaps`] are
//!   removed from it: exactly those, no more and no fewer;
//! - the rendering without a display input is the rendering with one, less
//!   exactly the fields in [`display_fields`].
//!
//! When the Python's plan did not compile (a cycle, an unknown
//! prerequisite), its findings about what discovery read are left out: the
//! core reports no graph for such a run (rule F3), so it has none of them
//! (flyingrobots/taskalisk#44).
//!
//! One intended difference, which is not a gap: [`INTENDED_DIFFERENCE`].

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use issue_dag_bundle::load;
use issue_dag_core::{IssueRef, RecordedForge, plan};
use serde_json::Value;
use taskalisk::render::{Display, NotRendered, render};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn fixtures() -> PathBuf {
    root().join("tests/fixtures/render")
}

/// The bundle a fixture plans: a variant's, written by
/// `tests/capture_render_parity.py` beside the fixtures, or a corpus
/// case's; `<case>--titles` is `<case>` with titles that hold what JSON
/// must escape.
fn bundle_text(case: &str) -> String {
    let variant = fixtures().join("bundles").join(format!("{case}.json"));
    if let Ok(text) = fs::read_to_string(&variant) {
        return text;
    }
    let case = case.strip_suffix("--titles").unwrap_or(case);
    let path = root()
        .join("tests/fixtures/issue-dag/corpus/cases/graph")
        .join(case)
        .join("bundle.json");
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

fn rendered(case: &str, display: Option<&Display>) -> Result<String, String> {
    let bundle = load(&bundle_text(case)).map_err(|e| format!("bundle rejected: {e}"))?;
    let forge = RecordedForge::new(&bundle.observations);
    let outcome = plan(&bundle.parameters, &forge).map_err(|e| e.to_string())?;
    render(&bundle.parameters, &outcome, display).map_err(|e| format!("not rendered: {e:?}"))
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

fn text(value: &Value) -> Option<String> {
    value.as_str().map(str::to_owned)
}

fn reference(value: &Value) -> Option<IssueRef> {
    value.as_str().and_then(IssueRef::parse)
}

fn string_lists(value: &Value) -> BTreeMap<String, Vec<String>> {
    value
        .as_object()
        .into_iter()
        .flatten()
        .map(|(k, v)| {
            let items = v.as_array().into_iter().flatten().filter_map(text);
            (k.clone(), items.collect())
        })
        .collect()
}

/// The display input the Python's lines show: what the adapters will read.
fn display_of(python: &[Value]) -> Display {
    let mut d = Display::default();
    let mut issue = |id: &Value, title: &Value, url: &Value| {
        let Some(id) = reference(id) else { return };
        if let Some(title) = text(title).filter(|t| t != "(untrusted issue)") {
            d.titles.insert(id.clone(), title);
        }
        if let Some(url) = text(url) {
            d.urls.insert(id, url);
        }
    };
    for line in python {
        let detail = &line["detail"];
        match (line["event"].as_str(), line["code"].as_str()) {
            (Some("frontier_node" | "node"), _) => {
                issue(&line["id"], &line["title"], &line["url"]);
            }
            (Some("finding"), Some("container.excluded" | "issue.unmodeled" | "issue.opaque")) => {
                issue(&detail["id"], &detail["title"], &detail["url"]);
            }
            (Some("finding"), Some("parent.not_planned")) => {
                issue(&detail["parent"], &detail["title"], &Value::Null);
            }
            _ => {}
        }
    }
    for line in python {
        if matches!(line["event"].as_str(), Some("frontier_node" | "node")) {
            let Some(id) = reference(&line["id"]) else {
                continue;
            };
            for pr in line["linked_open_prs"].as_array().into_iter().flatten() {
                if let (Some(n), Some(url)) = (pr["number"].as_u64(), text(&pr["url"])) {
                    d.pull_request_urls.insert(n, url);
                }
            }
            let branches: Vec<String> = line["recoverable_branches"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(text)
                .collect();
            if !branches.is_empty() {
                d.recoverable_branches.insert(id, branches);
            }
        }
        if line["event"] == "plan" {
            let trust = &line["source"]["trust"];
            d.codeowners = string_lists(&trust["codeowners"]);
            d.codeowners_teams_not_expanded = string_lists(&trust["codeowners_teams_not_expanded"]);
        }
    }
    d
}

/// Whether the case's 1.x document holds an intended difference or a gap:
/// then the Rust `artifact_hash` digests the Rust document, and is not the
/// Python's (`docs/topics/output/README.md`). Only its form is asserted.
fn hash_differs(python: &[Value]) -> bool {
    python[0]["outcome"] != "compiled"
        || python.iter().any(|l| {
            matches!(
                l["code"].as_str(),
                Some(
                    "frontmatter.violation"
                        | "frontmatter.warning"
                        | "issue.untrusted"
                        | "pull_request.untrusted"
                )
            )
        })
}

/// The fields of a Python line the renderer does not write, given a
/// display input, as paths from the line; `*` stands for every item of a
/// list.
fn gaps(line: &Value) -> Vec<&'static str> {
    match line["event"].as_str() {
        Some("finding") => match line["code"].as_str() {
            // The trust gate's reasons: flyingrobots/taskalisk#46.
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
            _ => Vec::new(),
        },
        _ => Vec::new(),
    }
}

/// The fields of a line that only the display input gives.
fn display_fields(line: &Value) -> Vec<&'static str> {
    const NODE: [&str; 4] = [
        "title",
        "url",
        "recoverable_branches",
        "linked_open_prs/*/url",
    ];
    let codeowners = line
        .pointer("/source/trust/codeowners")
        .is_some_and(|c| !c.is_null());
    match line["event"].as_str() {
        Some("plan") => {
            let mut out = Vec::new();
            if codeowners {
                out.extend([
                    "source/trust/codeowners",
                    "source/trust/codeowners_teams_not_expanded",
                ]);
            }
            out
        }
        Some("frontier_node" | "node") => NODE.to_vec(),
        Some("batch") => vec!["members/*/title", "members/*/url"],
        Some("finding") => match line["code"].as_str() {
            Some("container.excluded" | "issue.opaque" | "parent.not_planned") => {
                vec!["detail/title"]
            }
            Some("issue.unmodeled") => vec!["detail/title", "detail/url"],
            _ => Vec::new(),
        },
        _ => Vec::new(),
    }
}

/// Checks a plan line's `artifact_hash` is 64 lower-case hexadecimal
/// digits, and removes it: the caller compares the rest.
fn hash_removed(mut plan: Value, what: &str, problems: &mut Vec<String>) -> Value {
    let hash = plan.as_object_mut().and_then(|o| o.remove("artifact_hash"));
    let well_formed = hash.as_ref().and_then(Value::as_str).is_some_and(|h| {
        h.len() == 64
            && h.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    });
    if !well_formed {
        problems.push(format!(
            "{what}: artifact_hash is not 64 hex digits: {hash:?}"
        ));
    }
    plan
}

/// Removes one path from a value; whether anything was there.
fn remove(value: &mut Value, path: &[&str]) -> bool {
    match path {
        [] => false,
        ["*", rest @ ..] => value.as_array_mut().is_some_and(|items| {
            // From every item, so no short circuit.
            let mut all = true;
            for item in items {
                all &= remove(item, rest);
            }
            all
        }),
        [key] => value
            .as_object_mut()
            .is_some_and(|o| o.remove(*key).is_some()),
        [key, rest @ ..] => value.get_mut(*key).is_some_and(|v| remove(v, rest)),
    }
}

/// The line without these fields; a field the line lacks is a problem.
fn without(line: &Value, fields: &[&str], problems: &mut Vec<String>) -> Value {
    let mut out = line.clone();
    for field in fields {
        let path: Vec<&str> = field.split('/').collect();
        if !remove(&mut out, &path) {
            problems.push(format!("the line has no {field}: {line}"));
        }
    }
    out
}

/// A finding about what discovery read (rule W1).
fn is_discovery_finding(line: &Value) -> bool {
    line["event"] == "finding"
        && matches!(
            line["code"].as_str(),
            Some(
                "container.excluded"
                    | "issue.unmodeled"
                    | "issue.untrusted"
                    | "pull_request.untrusted"
                    | "issue.opaque"
                    | "parent.not_planned"
            )
        )
}

/// The intended difference: a `frontmatter.violation` or
/// `frontmatter.warning` compares by its `code` and `subject` alone, as a
/// set. Reason: the skill reads those two, and the message is prose that
/// neither the schema nor the specification fixes (the Python writes one
/// line per message with the value in it, the core one per rule with fixed
/// text).
const INTENDED_DIFFERENCE: &str = "frontmatter.";

/// The lines in the form they compare in: every line but the
/// `frontmatter.*` findings in order, and those as a set of (code, subject)
/// ([`INTENDED_DIFFERENCE`]).
fn comparable(lines: Vec<Value>) -> (Vec<Value>, BTreeSet<(String, String)>) {
    let mut ordered = Vec::new();
    let mut frontmatter = BTreeSet::new();
    for line in lines {
        match line["code"].as_str() {
            Some(code) if line["event"] == "finding" && code.starts_with(INTENDED_DIFFERENCE) => {
                let subject = line["subject"].as_str().unwrap_or_default().to_owned();
                frontmatter.insert((code.to_owned(), subject));
            }
            _ => ordered.push(line),
        }
    }
    (ordered, frontmatter)
}

fn compare(want: Vec<Value>, got: Vec<Value>, what: &str, problems: &mut Vec<String>) {
    let ((want, want_frontmatter), (got, got_frontmatter)) = (comparable(want), comparable(got));
    if want_frontmatter != got_frontmatter {
        problems.push(format!(
            "{what}: frontmatter findings {want_frontmatter:?}, rust {got_frontmatter:?}"
        ));
    }
    if want.len() != got.len() {
        problems.push(format!("{what}: {} lines, rust {}", want.len(), got.len()));
    }
    for (n, (w, g)) in want.iter().zip(&got).enumerate() {
        if w != g {
            problems.push(format!("{what} line {}:\n  want {w}\n  rust {g}", n + 1));
        }
    }
}

#[test]
fn every_agreed_case_renders_as_the_python_does() {
    let bless = std::env::var_os("TASKALISK_BLESS").is_some();
    let names = cases();
    assert!(names.len() > 100, "too few cases: {}", names.len());
    let mut failures = Vec::new();
    // The cases whose artifact_hash must equal the Python's.
    let mut equal_hashes = 0;
    for case in &names {
        let python_text =
            fs::read_to_string(fixtures().join("python").join(format!("{case}.jsonl")))
                .expect("the Python fixture");
        let python = lines(&python_text);
        let display = display_of(&python);
        let text = match rendered(case, Some(&display)) {
            Ok(text) => text,
            Err(why) => {
                failures.push(format!("{case}: {why}"));
                continue;
            }
        };
        let mut problems = Vec::new();
        if rendered(case, Some(&display)).as_deref() != Ok(text.as_str()) {
            problems.push("two renderings differ".to_owned());
        }
        let recorded = fixtures().join("rust").join(format!("{case}.jsonl"));
        if bless {
            fs::create_dir_all(recorded.parent().expect("parent")).expect("mkdir");
            fs::write(&recorded, &text).expect("write the recording");
        } else if fs::read_to_string(&recorded).ok().as_deref() != Some(text.as_str()) {
            problems.push(format!(
                "differs from tests/fixtures/render/rust/{case}.jsonl (TASKALISK_BLESS=1 rewrites it)"
            ));
        }
        let got = lines(&text);

        // With a display input, against the Python.
        let compiled = python[0]["outcome"] == "compiled";
        let mut want: Vec<Value> = python
            .iter()
            .filter(|l| compiled || !is_discovery_finding(l))
            .map(|l| without(l, &gaps(l), &mut problems))
            .collect();
        let mut theirs = got.clone();
        if hash_differs(&python) {
            want[0] = hash_removed(want[0].clone(), "python", &mut problems);
            theirs[0] = hash_removed(theirs[0].clone(), "rust", &mut problems);
        } else {
            equal_hashes += 1;
        }
        compare(want, theirs, "python", &mut problems);

        // Without one, against the rendering with one. The hash digests a
        // different document, so only its form is compared.
        match rendered(case, None) {
            Ok(bare) => {
                if rendered(case, None).as_deref() != Ok(bare.as_str()) {
                    problems.push("two renderings without display differ".to_owned());
                }
                let mut want: Vec<Value> = got
                    .iter()
                    .map(|l| without(l, &display_fields(l), &mut problems))
                    .collect();
                let mut bare = lines(&bare);
                want[0] = hash_removed(want[0].clone(), "with display", &mut problems);
                bare[0] = hash_removed(bare[0].clone(), "without display", &mut problems);
                compare(want, bare, "without display", &mut problems);
            }
            Err(why) => problems.push(format!("without display: {why}")),
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
    // 76 corpus cases, the one planned again with hostile titles, and the
    // variants d9-container--opaque-child, --opaque-children-in-order-read,
    // --traversal-order, --not-planned-in-blocked-by-order and
    // --not-planned-per-task-order (the pull request and untrusted variants
    // hold untrusted issues or pulls; the unknown-and-cycle one compiles
    // nothing).
    assert_eq!(
        equal_hashes, 82,
        "the cases whose artifact_hash is the Python's"
    );
}

#[test]
fn a_rejected_or_incomplete_run_has_no_result_lines() {
    let outcome_of = |case: &str| {
        let bundle = load(&bundle_text(case)).expect("bundle");
        let forge = RecordedForge::new(&bundle.observations);
        let outcome = plan(&bundle.parameters, &forge).expect("recorded");
        render(&bundle.parameters, &outcome, None)
    };
    assert_eq!(
        outcome_of("i2-root-not-a-reference"),
        Err(NotRendered::Rejected)
    );
    assert_eq!(
        outcome_of("i5-issue-unavailable"),
        Err(NotRendered::Incomplete)
    );
}
