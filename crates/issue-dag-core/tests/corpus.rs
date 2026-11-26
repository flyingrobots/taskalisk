//! Runs every document-level case of the vendored conformance corpus
//! (`tests/fixtures/issue-dag/corpus/cases/document/`) through the crate.
//!
//! - A normative case passes when every member of its expected result equals
//!   the crate's (corpus rule CC8): `violations` and `warnings` compare as sets.
//! - A characterisation case with a `normative_case` (a `--python` twin)
//!   records what the Python computes where it disagrees with the
//!   specification. The crate must match the normative case instead, on the
//!   twin's own input.
//! - A characterisation case without a normative twin (the census shapes) is
//!   one where the Python and the specification agree; the crate must equal
//!   its expected result exactly.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use issue_dag_core::{IssueRef, Judgement, Record, Status, TaskType, admit};
use serde_json::{Map, Value, json};

fn corpus_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/issue-dag/corpus/cases/document")
}

fn read_json(path: &Path) -> Value {
    let text = fs::read_to_string(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

fn record_json(record: &Record) -> Value {
    let refs = |list: &Option<Vec<IssueRef>>| {
        list.as_ref().map_or(Value::Null, |l| {
            Value::Array(l.iter().map(|r| json!(r.to_string())).collect())
        })
    };
    json!({
        "version": record.version(),
        "id": record.id.to_string(),
        "kind": record.kind.as_str(),
        "type": record.task_type.map(TaskType::as_str),
        "blocked_by": refs(&record.blocked_by),
        "children": refs(&record.children),
        "size_hours": record.size_hours,
        "holds": record.holds.iter().collect::<Vec<_>>(),
        "meters": record.meters.iter().map(|m| json!([m.name, m.slots])).collect::<Vec<_>>(),
        "status": record.status.map(Status::as_str),
    })
}

fn labels(set: &BTreeSet<issue_dag_core::Label>) -> Value {
    let mut list: Vec<&str> = set.iter().map(|l| l.as_str()).collect();
    list.sort_unstable();
    json!(list)
}

/// The crate's result in the form of corpus rule CC5.
fn result_json(input: &Value) -> Value {
    let body = input["body"].as_str().expect("input.body is a string");
    let address = input["address"].as_str().map(|a| {
        IssueRef::parse(a).unwrap_or_else(|| panic!("input.address {a:?} is a reference"))
    });
    match admit(body, address.as_ref()) {
        Judgement::NoDocument => json!({"result": "no-document"}),
        Judgement::Valid { record, warnings } => json!({
            "result": "valid",
            "record": record_json(&record),
            "warnings": labels(&warnings),
        }),
        Judgement::Invalid(v) => json!({
            "result": "invalid",
            "violations": labels(&v.violations),
            "warnings": labels(&v.warnings),
        }),
    }
}

fn as_set(value: &Value) -> Option<BTreeSet<String>> {
    value
        .as_array()
        .map(|a| a.iter().map(ToString::to_string).collect())
}

/// CC8 for a normative case: every member the expected result holds equals
/// the actual one; `violations` and `warnings` compare as sets.
fn normative_mismatch(expected: &Map<String, Value>, actual: &Value) -> Option<String> {
    for (member, want) in expected {
        let got = &actual[member.as_str()];
        let equal = match member.as_str() {
            "violations" | "warnings" => as_set(want) == as_set(got),
            _ => want == got,
        };
        if !equal {
            return Some(format!("{member}: expected {want}, got {got}"));
        }
    }
    None
}

#[test]
fn every_document_case_of_the_corpus() {
    let mut names: Vec<String> = fs::read_dir(corpus_dir())
        .expect("the vendored corpus is present")
        .map(|e| {
            e.expect("directory entry")
                .file_name()
                .into_string()
                .expect("UTF-8 name")
        })
        .collect();
    names.sort();
    assert!(!names.is_empty(), "no document cases found");

    let mut failures = Vec::new();
    let (mut normative, mut twins, mut census) = (0, 0, 0);
    for name in &names {
        let dir = corpus_dir().join(name);
        let case = read_json(&dir.join("case.json"));
        let input = read_json(&dir.join("input.json"));
        let actual = result_json(&input);
        let mismatch = match (case["kind"].as_str(), case["normative_case"].as_str()) {
            (Some("normative"), _) => {
                normative += 1;
                let expected = read_json(&dir.join("expected.json"));
                normative_mismatch(expected.as_object().expect("object"), &actual)
            }
            (Some("characterisation"), Some(twin)) => {
                twins += 1;
                let twin_name = twin.strip_prefix("document/").expect("a document case");
                let twin_dir = corpus_dir().join(twin_name);
                assert_eq!(
                    read_json(&twin_dir.join("input.json")),
                    input,
                    "{name}: the twin's input differs from its normative case's"
                );
                let expected = read_json(&twin_dir.join("expected.json"));
                normative_mismatch(expected.as_object().expect("object"), &actual)
            }
            (Some("characterisation"), None) => {
                census += 1;
                let expected = read_json(&dir.join("expected.json"));
                (expected != actual).then(|| format!("expected {expected}, got {actual}"))
            }
            (kind, _) => Some(format!("unknown case kind {kind:?}")),
        };
        if let Some(why) = mismatch {
            failures.push(format!("{name}: {why}"));
        }
    }

    println!(
        "document cases: {} ({normative} normative, {twins} --python twins, {census} other characterisation); {} failing",
        names.len(),
        failures.len()
    );
    assert_eq!(normative + twins + census, names.len());
    assert!(
        failures.is_empty(),
        "{} of {} document cases fail:\n{}",
        failures.len(),
        names.len(),
        failures.join("\n")
    );
}
