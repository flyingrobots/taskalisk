//! The evaluation record, `taskalisk-evaluation/1`, and its replay rule
//! (flyingrobots/taskalisk#30).
//!
//! - For every graph case of the vendored corpus, a record made from the
//!   case's bundle replays to the same result, byte for byte.
//! - A record whose input is not retained, or whose retained input lacks a
//!   slot the run reads, reports replay unavailable instead of guessing.

use std::fs;
use std::path::{Path, PathBuf};

use issue_dag_bundle::{
    EvaluationError, EvaluationRecord, Evaluator, Evaluators, RECORD_VERSION, Replay, evaluate,
    load, replay, unretained,
};
use issue_dag_core::{RecordedForge, plan};
use serde_json::{Value, json};

fn corpus_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/issue-dag/corpus/cases/graph")
}

fn evaluator() -> Evaluator {
    Evaluator {
        name: "taskalisk".to_owned(),
        version: "0.0.0-test".to_owned(),
    }
}

/// The example of `corpus/bundle.md`, with a complete body.
fn example() -> Value {
    json!({
        "bundle": "issue-dag-observations/1",
        "format": "issue-dag/2",
        "profile": "issue-dag-planning/2",
        "parameters": {
            "home": "o/r",
            "roots": ["o/r#1"],
            "read_scope": {"owners": ["o"], "repositories": []},
            "trust": {"policy": "taskalisk/threat-model", "logins": ["dev"], "codeowners": false},
            "capacities": {"gpu": 2}
        },
        "observations": {
            "home_open_pull_requests": {"value": []},
            "issues": {
                "o/r#1": {"value": {
                    "address": "o/r#1", "pull_request": false, "state": "open", "state_reason": null,
                    "author": {"login": "o", "type": "User"}, "author_association": "OWNER",
                    "body": {"value": {"text": "Plain body.", "editors": [{"login": "o", "type": "User"}]}}
                }},
                "o/r#2": {"unavailable": "HTTP 502 from the issues endpoint"}
            },
            "permissions": {"o/r": {"carol": {"value": null}}}
        }
    })
}

fn record_of(bundle: &Value) -> Value {
    let record = evaluate(&bundle.to_string(), &evaluator()).expect("the bundle evaluates");
    serde_json::from_str(&record.to_json()).expect("a record is JSON")
}

fn replay_value(record: &Value) -> Replay {
    replay(&record.to_string(), &evaluator()).expect("a well-formed record")
}

fn read_json(path: &Path) -> Value {
    let text = fs::read_to_string(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// The expected result the crate is held to: a `--python` twin's is its
/// normative case's (corpus rule CC4).
fn expected_of(dir: &Path) -> Value {
    let case = read_json(&dir.join("case.json"));
    case["normative_case"].as_str().map_or_else(
        || read_json(&dir.join("expected.json")),
        |twin| {
            let name = twin.strip_prefix("graph/").expect("a graph case");
            read_json(&dir.with_file_name(name).join("expected.json"))
        },
    )
}

/// The graph cases whose bundle lacks a slot the run reads (CC6
/// `unusable`, bundle rule OB5), twins included, and the cases that have a
/// result. A case cannot move between the two without changing these.
const UNUSABLE_CASES: usize = 22;
const RECORDED_CASES: usize = 205;

#[test]
fn every_graph_case_replays_byte_for_byte() {
    let mut names: Vec<_> = fs::read_dir(corpus_dir())
        .expect("the vendored corpus is present")
        .map(|e| e.expect("directory entry").path())
        .collect();
    names.sort();
    assert!(!names.is_empty(), "no graph cases found");
    let mut failures = Vec::new();
    let (mut unusable, mut recorded_cases) = (0, 0);
    for dir in &names {
        let name = dir.file_name().and_then(|n| n.to_str()).unwrap_or("?");
        let bundle = fs::read_to_string(dir.join("bundle.json")).expect("bundle.json");
        let expected = expected_of(dir);
        if expected["outcome"] == "unusable" {
            // OB5: no record, and the slot refused is the one the case
            // expects (OB16).
            unusable += 1;
            match evaluate(&bundle, &evaluator()) {
                Err(EvaluationError::Missing(m)) if json!(m.path) == expected["missing"] => {}
                other => failures.push(format!(
                    "{name}: expected no record for want of {}, got {other:?}",
                    expected["missing"]
                )),
            }
            continue;
        }
        recorded_cases += 1;
        let record = match evaluate(&bundle, &evaluator()) {
            Ok(record) => record,
            Err(e) => {
                failures.push(format!("{name}: no record: {e}"));
                continue;
            }
        };
        let text = record.to_json();
        let recorded = serde_json::to_string(record.result()).expect("a result serialises");
        match replay(&text, &evaluator()) {
            Ok(Replay::Reproduced { result, .. }) if result == recorded => {}
            other => failures.push(format!("{name}: replay gave {other:?}")),
        }
        // The record reads back to the same bytes, and evaluating the same
        // bundle again writes the same record.
        let reread = EvaluationRecord::read(&text).map(|r| r.to_json());
        if reread.as_deref() != Ok(text.as_str()) {
            failures.push(format!(
                "{name}: the record does not read back to its bytes"
            ));
        }
        let again = evaluate(&bundle, &evaluator()).map(|r| r.to_json());
        if again.as_deref() != Ok(text.as_str()) {
            failures.push(format!("{name}: evaluating twice gives two records"));
        }
    }
    assert_eq!(
        (unusable, recorded_cases),
        (UNUSABLE_CASES, RECORDED_CASES),
        "graph cases refused as unusable, and recorded"
    );
    assert_eq!(unusable + recorded_cases, names.len());
    assert!(
        failures.is_empty(),
        "{} of {} graph cases fail:\n{}",
        failures.len(),
        names.len(),
        failures.join("\n")
    );
}

#[test]
fn a_record_names_formats_profile_evaluator_scope_and_facts_not_observed() {
    let record = record_of(&example());
    assert_eq!(record["record"], json!(RECORD_VERSION));
    assert_eq!(record["formats"], json!(["issue-dag/2"]));
    assert_eq!(record["profile"], json!("issue-dag-planning/2"));
    assert_eq!(
        record["evaluator"],
        json!({"name": "taskalisk", "version": "0.0.0-test"})
    );
    assert_eq!(
        record["discovery"],
        json!({
            "home": "o/r",
            "roots": ["o/r#1"],
            "read_scope": {"owners": ["o"], "repositories": []},
            "trust_policy": "taskalisk/threat-model"
        })
    );
    assert_eq!(
        record["not_observed"],
        json!({"value": [
            {"at": "observations.issues[\"o/r#2\"]", "unavailable": "HTTP 502 from the issues endpoint"}
        ]})
    );
    assert_eq!(
        record["observations"],
        json!({"value": example()}),
        "the bundle is retained whole"
    );
    assert_eq!(record["result"]["outcome"], json!("planned"));
}

#[test]
fn every_kind_of_unavailable_slot_is_a_fact_not_observed() {
    let mut bundle = example();
    bundle["parameters"]["roots"] = json!([]);
    bundle["parameters"]["trust"]["codeowners"] = json!(true);
    let o = &mut bundle["observations"];
    o["home_open_issues"] = json!({"unavailable": "truncated"});
    o["home_open_pull_requests"] = json!({"value": [{
        "number": 3, "repository": "o/r", "head_repository": "o/r", "cross_repository": false,
        "author": null, "draft": {"unavailable": "draft flag was a string"}, "closes": []
    }]});
    o["issues"]["o/r#1"]["value"]["body"] = json!({"unavailable": "body timed out"});
    o["permissions"]["o/r"]["carol"] = json!({"unavailable": "HTTP 403"});
    o["codeowners"] = json!({"o/r": {"unavailable": "HTTP 500"}});
    let record = record_of(&bundle);
    assert_eq!(
        record["not_observed"],
        json!({"value": [
            {"at": "observations.codeowners[\"o/r\"]", "unavailable": "HTTP 500"},
            {"at": "observations.home_open_issues", "unavailable": "truncated"},
            {"at": "observations.home_open_pull_requests[0].draft", "unavailable": "draft flag was a string"},
            {"at": "observations.issues[\"o/r#1\"].body", "unavailable": "body timed out"},
            {"at": "observations.issues[\"o/r#2\"]", "unavailable": "HTTP 502 from the issues endpoint"},
            {"at": "observations.permissions[\"o/r\"][\"carol\"]", "unavailable": "HTTP 403"}
        ]})
    );
    assert_eq!(record["result"], json!({"outcome": "incomplete"}));
    assert!(matches!(replay_value(&record), Replay::Reproduced { .. }));
}

#[test]
fn observations_not_retained_make_replay_unavailable() {
    let mut record = record_of(&example());
    record["observations"] = json!({"unavailable": "the run kept no bundle"});
    record["not_observed"] = json!({"unavailable": "the run kept no bundle"});
    match replay_value(&record) {
        Replay::Unavailable(why) => assert!(why.contains("the run kept no bundle"), "{why}"),
        other => panic!("expected replay unavailable, got {other:?}"),
    }
}

#[test]
fn a_retained_bundle_that_lacks_a_slot_the_run_reads_makes_replay_unavailable() {
    let mut record = record_of(&example());
    let issue = &mut record["observations"]["value"]["observations"]["issues"]["o/r#1"]["value"];
    issue
        .as_object_mut()
        .expect("an issue")
        .remove("body")
        .expect("a body");
    match replay_value(&record) {
        Replay::Unavailable(why) => assert!(why.contains("the body of o/r#1"), "{why}"),
        other => panic!("expected replay unavailable, got {other:?}"),
    }

    let mut record = record_of(&example());
    record["observations"]["value"]["observations"]
        .as_object_mut()
        .expect("observations")
        .remove("home_open_pull_requests");
    assert!(matches!(replay_value(&record), Replay::Unavailable(_)));
}

#[test]
fn a_retained_input_that_is_not_a_bundle_makes_replay_unavailable() {
    let mut record = record_of(&example());
    record["observations"]["value"]["bundle"] = json!("issue-dag-observations/0");
    match replay_value(&record) {
        Replay::Unavailable(why) => assert!(why.contains("not a bundle"), "{why}"),
        other => panic!("expected replay unavailable, got {other:?}"),
    }
}

#[test]
fn a_record_of_another_profile_is_not_replayed_by_this_evaluator() {
    let mut record = record_of(&example());
    record["profile"] = json!("issue-dag-planning/3");
    record["observations"]["value"]["profile"] = json!("issue-dag-planning/3");
    match replay_value(&record) {
        Replay::Unavailable(why) => assert!(why.contains("issue-dag-planning/3"), "{why}"),
        other => panic!("expected replay unavailable, got {other:?}"),
    }
}

#[test]
fn a_changed_result_is_reported_as_differing_never_reproduced() {
    let mut record = record_of(&example());
    let original = serde_json::to_string(&record["result"]).expect("a result");
    record["result"]["ready"] = json!([]);
    match replay_value(&record) {
        Replay::Differs {
            recorded,
            recomputed,
            ..
        } => {
            assert_eq!(recomputed, original);
            assert_ne!(recorded, recomputed);
        }
        other => panic!("expected a difference, got {other:?}"),
    }
}

#[test]
fn a_record_that_contradicts_its_bundle_is_refused() {
    for (member, value) in [
        (
            "discovery",
            json!({"home": "o/x", "roots": [], "read_scope": {"owners": ["o"], "repositories": []}, "trust_policy": "taskalisk/threat-model"}),
        ),
        ("not_observed", json!({"value": []})),
        ("formats", json!(["issue-dag/3"])),
        ("profile", json!("issue-dag-planning/3")),
    ] {
        let mut record = record_of(&example());
        record[member] = value;
        let error = replay(&record.to_string(), &evaluator())
            .expect_err("the record contradicts its bundle");
        assert!(error.at.starts_with(member), "{member}: {error}");
    }
}

#[test]
fn a_malformed_record_is_refused() {
    let record = record_of(&example());
    let mut extra = record.clone();
    extra["comment"] = json!("not a member");
    assert!(
        replay(&extra.to_string(), &evaluator()).is_err(),
        "an undefined member"
    );
    for member in [
        "record",
        "formats",
        "profile",
        "evaluator",
        "discovery",
        "not_observed",
        "observations",
        "result",
    ] {
        let mut lacking = record.clone();
        lacking.as_object_mut().expect("an object").remove(member);
        assert!(
            replay(&lacking.to_string(), &evaluator()).is_err(),
            "lacks {member}"
        );
    }
    let mut version = record.clone();
    version["record"] = json!("taskalisk-evaluation/0");
    assert!(
        replay(&version.to_string(), &evaluator()).is_err(),
        "another version"
    );
    let text = record.to_string();
    let repeated = format!("{},\"record\":\"x\"}}", &text[..text.len() - 1]);
    assert!(
        replay(&repeated, &evaluator()).is_err(),
        "a member given twice"
    );
    assert!(replay("not json", &evaluator()).is_err());
}

#[test]
fn a_run_that_kept_no_bundle_records_that_replay_is_unavailable() {
    let bundle = load(&example().to_string()).expect("a bundle");
    let outcome = plan(
        &bundle.parameters,
        &RecordedForge::new(&bundle.observations),
    )
    .expect("a run");
    let record = unretained(&bundle.parameters, &outcome, &evaluator(), "capture is off");
    let value: Value = serde_json::from_str(&record.to_json()).expect("JSON");
    assert_eq!(
        value["observations"],
        json!({"unavailable": "capture is off"})
    );
    assert_eq!(
        value["not_observed"],
        json!({"unavailable": "capture is off"})
    );
    assert_eq!(value["result"], record_of(&example())["result"]);
    assert!(matches!(
        replay(&record.to_json(), &evaluator()),
        Ok(Replay::Unavailable(_))
    ));
}

#[test]
fn replay_reports_the_recorded_and_the_replaying_evaluator() {
    let mut record = record_of(&example());
    let other = Evaluator {
        name: "taskalisk".to_owned(),
        version: "9.9.9".to_owned(),
    };
    match replay(&record.to_string(), &other).expect("a well-formed record") {
        Replay::Reproduced { evaluators, .. } => {
            assert_eq!(
                evaluators,
                Evaluators {
                    recorded: evaluator(),
                    replaying: other.clone(),
                }
            );
            assert!(evaluators.changed());
        }
        unexpected => panic!("expected the result reproduced, got {unexpected:?}"),
    }
    match replay_value(&record) {
        Replay::Reproduced { evaluators, .. } => assert!(!evaluators.changed()),
        unexpected => panic!("expected the result reproduced, got {unexpected:?}"),
    }
    record["result"]["ready"] = json!([]);
    match replay(&record.to_string(), &other).expect("a well-formed record") {
        Replay::Differs { evaluators, .. } => {
            assert_eq!(evaluators.recorded, evaluator());
            assert_eq!(evaluators.replaying, other);
            assert!(
                evaluators.changed(),
                "the difference may be the evaluator's"
            );
        }
        unexpected => panic!("expected a difference, got {unexpected:?}"),
    }
    match replay_value(&record) {
        Replay::Differs { evaluators, .. } => {
            assert!(
                !evaluators.changed(),
                "the same evaluator differs from its record"
            );
        }
        unexpected => panic!("expected a difference, got {unexpected:?}"),
    }
}
