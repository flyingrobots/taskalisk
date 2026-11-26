//! The bundle reader against bundle rules OB1 to OB13.

use std::fs;
use std::path::Path;

use issue_dag_bundle::{BundleError, load};
use issue_dag_core::{IssueRef, Observed, Outcome, RecordedForge, Repo, plan};
use serde_json::{Value, json};

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
                    "body": {"value": {"text": "Plain body.", "editors": [{"login": "o", "type": "User"}, null]}}
                }},
                "o/r#2": {"unavailable": "HTTP 502 from the issues endpoint"}
            },
            "permissions": {"o/r": {"carol": {"value": null}}}
        }
    })
}

fn reject(bundle: &Value) -> BundleError {
    load(&bundle.to_string()).expect_err("the bundle must be rejected")
}

#[test]
fn the_example_bundle_loads() {
    let bundle = load(&example().to_string()).expect("the example loads");
    assert_eq!(bundle.parameters.home, Repo::parse("o/r").expect("repo"));
    assert_eq!(bundle.parameters.roots, ["o/r#1"]);
    assert_eq!(bundle.parameters.capacities.get("gpu"), Some(&2));
    let two = IssueRef::parse("o/r#2").expect("reference");
    assert_eq!(
        bundle.observations.issues.get(&two),
        Some(&Observed::Unavailable(
            "HTTP 502 from the issues endpoint".to_owned()
        ))
    );
    assert!(bundle.observations.home_open_issues.is_none());
    assert!(bundle.observations.codeowners.is_none());
}

#[test]
fn ob1_another_version_or_member_set_is_rejected() {
    let mut b = example();
    b["bundle"] = json!("issue-dag-observations/2");
    reject(&b);
    let mut b = example();
    b["extra"] = json!(1);
    reject(&b);
    let mut b = example();
    b.as_object_mut().expect("object").remove("profile");
    reject(&b);
    reject(&json!([]));
    assert!(load("{").is_err());
}

#[test]
fn ob3_parameters_have_exactly_their_members() {
    let mut b = example();
    b["parameters"]["extra"] = json!(true);
    reject(&b);
    let mut b = example();
    b["parameters"]["capacities"]["gpu"] = json!(0);
    reject(&b);
    let mut b = example();
    b["parameters"]["read_scope"] = json!({"owners": [], "repositories": ["o/s"]});
    // The read scope must include the home repository.
    reject(&b);
    let mut b = example();
    b["parameters"]["trust"]["codeowners"] = json!("yes");
    reject(&b);
}

#[test]
fn ob3_roots_and_policy_are_recorded_unvalidated() {
    let mut b = example();
    b["parameters"]["roots"] = json!(["not a reference"]);
    b["parameters"]["trust"]["policy"] = json!("someone/else");
    let bundle = load(&b.to_string()).expect("a rejected run can be recorded");
    assert_eq!(bundle.parameters.roots, ["not a reference"]);
    assert_eq!(bundle.parameters.trust.policy, "someone/else");
}

#[test]
fn ob4_a_slot_has_exactly_one_member_and_a_reason() {
    for slot in [
        json!({}),
        json!({"value": [], "unavailable": "x"}),
        json!({"unavailable": ""}),
        json!({"unavailable": 3}),
        json!([]),
    ] {
        let mut b = example();
        b["observations"]["home_open_pull_requests"] = slot;
        reject(&b);
    }
}

#[test]
fn ob6_the_home_listing_is_absent_when_the_run_has_roots() {
    let mut b = example();
    b["observations"]["home_open_issues"] = json!({"value": []});
    reject(&b);
    let mut b = example();
    b["parameters"]["roots"] = json!([]);
    b["observations"]["home_open_issues"] = json!({"value": ["o/r#1"]});
    let bundle = load(&b.to_string()).expect("loads");
    assert_eq!(
        bundle.observations.home_open_issues,
        Some(Observed::Value(vec![
            IssueRef::parse("o/r#1").expect("ref")
        ]))
    );
}

#[test]
fn ob7_a_pull_request_has_exactly_its_members_and_a_slot_for_draft() {
    let pull = json!({
        "number": 8, "repository": "o/r", "head_repository": null, "cross_repository": null,
        "author": null, "draft": {"unavailable": "not a boolean"}, "closes": ["o/r#1"]
    });
    let mut b = example();
    b["observations"]["home_open_pull_requests"] = json!({"value": [pull]});
    let bundle = load(&b.to_string()).expect("loads");
    let Some(Observed::Value(pulls)) = bundle.observations.home_open_pull_requests else {
        panic!("pull requests observed");
    };
    assert_eq!(
        pulls[0].draft,
        Observed::Unavailable("not a boolean".to_owned())
    );
    let mut extra = pull.clone();
    extra["title"] = json!("x");
    b["observations"]["home_open_pull_requests"] = json!({"value": [extra]});
    reject(&b);
    let mut other_repo = pull;
    other_repo["repository"] = json!("o/s");
    b["observations"]["home_open_pull_requests"] = json!({"value": [other_repo]});
    reject(&b);
}

#[test]
fn ob8_and_ob13_issue_keys_are_canonical_references() {
    let mut b = example();
    let one = b["observations"]["issues"]["o/r#1"].clone();
    b["observations"]["issues"]["O/r#1"] = one;
    reject(&b);
    let mut b = example();
    b["observations"]["issues"]["o/r#1"]["value"]["state"] = json!("merged");
    reject(&b);
    let mut b = example();
    b["observations"]["issues"]["o/r#1"]["value"]["author"] =
        json!({"login": "o", "type": "User", "id": 1});
    reject(&b);
}

#[test]
fn ob10_permission_logins_are_lower_case() {
    let mut b = example();
    b["observations"]["permissions"] = json!({"o/r": {"Carol": {"value": "write"}}});
    reject(&b);
}

#[test]
fn ob11_codeowners_is_present_exactly_when_the_policy_reads_it() {
    let mut b = example();
    b["observations"]["codeowners"] = json!({"o/r": {"value": null}});
    reject(&b);
    b["parameters"]["trust"]["codeowners"] = json!(true);
    load(&b.to_string()).expect("loads");
    b["observations"]["codeowners"] = json!({"o/r": {"value": {"path": "OWNERS", "text": "* @o"}}});
    reject(&b);
}

#[test]
fn every_bundle_of_the_corpus_loads() {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/fixtures/issue-dag/corpus/cases/graph");
    let mut count = 0;
    for entry in fs::read_dir(dir).expect("the vendored corpus is present") {
        let path = entry.expect("entry").path().join("bundle.json");
        let text = fs::read_to_string(&path).expect("bundle.json");
        if let Err(e) = load(&text) {
            panic!("{}: {e}", path.display());
        }
        count += 1;
    }
    assert!(count > 0);
}

#[test]
fn ob7_a_draft_flag_is_a_boolean_never_a_value_slot() {
    let mut pull = json!({
        "number": 8, "repository": "o/r", "head_repository": "o/r", "cross_repository": false,
        "author": {"login": "dev", "type": "User"}, "draft": true, "closes": []
    });
    let mut b = example();
    b["observations"]["home_open_pull_requests"] = json!({"value": [pull.clone()]});
    let bundle = load(&b.to_string()).expect("loads");
    let Some(Observed::Value(pulls)) = bundle.observations.home_open_pull_requests else {
        panic!("pull requests observed");
    };
    assert_eq!(pulls[0].draft, Observed::Value(true));
    pull["draft"] = json!({"value": true});
    b["observations"]["home_open_pull_requests"] = json!({"value": [pull]});
    reject(&b);
}

#[test]
fn a_member_given_twice_is_rejected_at_its_path() {
    // serde_json would keep the last value silently.
    let text = example().to_string();
    let twice = text.replacen(
        "\"bundle\":\"issue-dag-observations/1\"",
        "\"bundle\":\"issue-dag-observations/1\",\"bundle\":\"issue-dag-observations/1\"",
        1,
    );
    assert_ne!(twice, text);
    let error = load(&twice).expect_err("a repeated member is rejected");
    assert_eq!(error.at, "bundle");
    assert!(error.problem.contains("\"bundle\""), "{error}");

    let nested = text.replacen(
        "\"state\":\"open\"",
        "\"state\":\"closed\",\"state\":\"open\"",
        1,
    );
    assert_ne!(nested, text);
    let error = load(&nested).expect_err("a repeated nested member is rejected");
    assert_eq!(error.at, "observations.issues[\"o/r#1\"].value");
    assert!(error.problem.contains("\"state\""), "{error}");

    let in_list = text.replacen(
        "{\"login\":\"o\",\"type\":\"User\"},null",
        "{\"login\":\"o\",\"login\":\"x\",\"type\":\"User\"},null",
        1,
    );
    assert_ne!(in_list, text);
    let error = load(&in_list).expect_err("a repeated member in a list is rejected");
    assert_eq!(
        error.at,
        "observations.issues[\"o/r#1\"].value.body.value.editors[0]"
    );
}

#[test]
fn ob14_the_body_of_an_issue_the_run_never_reads_may_be_left_out() {
    // A stranger's root: the run never reads its body (threat model C15).
    let mut b = example();
    b["parameters"]["roots"] = json!(["o/r#3"]);
    b["observations"]["issues"]["o/r#3"] = json!({"value": {
        "address": "o/r#3", "pull_request": false, "state": "open", "state_reason": null,
        "author": {"login": "stranger", "type": "User"}, "author_association": "NONE"
    }});
    let bundle = load(&b.to_string()).expect("a bundle without that body loads");
    let three = IssueRef::parse("o/r#3").expect("reference");
    assert!(matches!(
        bundle.observations.issues.get(&three),
        Some(Observed::Value(_))
    ));
    assert_eq!(
        bundle.observations.bodies.get(&three),
        None,
        "left out, not read as empty"
    );
    // The body an issue slot holds is read into the bodies.
    let one = IssueRef::parse("o/r#1").expect("reference");
    assert!(matches!(
        bundle.observations.bodies.get(&one),
        Some(Observed::Value(body)) if body.text == "Plain body."
    ));
    let outcome = plan(
        &bundle.parameters,
        &RecordedForge::new(&bundle.observations),
    );
    assert!(
        matches!(outcome, Ok(Outcome::Planned { .. })),
        "the bundle replays: {outcome:?}"
    );

    // The body of a trusted root is read, so leaving it out is OB5.
    let mut b = example();
    let one = &mut b["observations"]["issues"]["o/r#1"]["value"];
    one.as_object_mut().expect("an object").remove("body");
    let bundle = load(&b.to_string()).expect("the bundle loads");
    let outcome = plan(
        &bundle.parameters,
        &RecordedForge::new(&bundle.observations),
    );
    let missing = outcome.expect_err("a body the run reads is missing, never empty");
    assert!(missing.what.contains("body of o/r#1"), "{missing}");
}
