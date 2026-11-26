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
//! A plan that did not compile (a cycle, an unknown prerequisite) is held
//! to its findings about what discovery read like any other: the core
//! reports them without the graph (decision D13, flyingrobots/taskalisk#44).
//!
//! One intended difference, which is not a gap: [`INTENDED_DIFFERENCE`].

mod common;

use std::collections::BTreeSet;
use std::fs;

use common::{cases, display_of, fixtures, hash_differs, lines, planned, python};
use serde_json::Value;
use taskalisk::render::{Display, NotRendered, render};

fn rendered(case: &str, display: Option<&Display>) -> Result<String, String> {
    let (parameters, outcome) = planned(case)?;
    render(&parameters, &outcome, display).map_err(|e| format!("not rendered: {e:?}"))
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
        let python = python(case);
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
        let mut want: Vec<Value> = python
            .iter()
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
    // 79 corpus cases (graph-cycle, g4-cycle and g4-downstream-of-a-cycle
    // among them), the one planned again with hostile titles, and the
    // variants d9-container--opaque-child, --opaque-children-in-order-read,
    // --traversal-order, --not-planned-in-blocked-by-order,
    // --not-planned-per-task-order and --traversal-order-and-cycle, and
    // discovery-unmodeled-home-issue--three-issue-cycle. The other variants
    // hold untrusted issues or pulls, or a frontmatter finding, as every run
    // with an unknown prerequisite does.
    assert_eq!(
        equal_hashes, 87,
        "the cases whose artifact_hash is the Python's"
    );
}

#[test]
fn a_rejected_or_incomplete_run_has_no_result_lines() {
    let outcome_of = |case: &str| {
        let (parameters, outcome) = planned(case).expect("recorded");
        render(&parameters, &outcome, None)
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
