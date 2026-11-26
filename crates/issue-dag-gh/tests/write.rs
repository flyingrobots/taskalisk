//! The gh adapter's write port against the fake `gh`: the writer's account
//! and the replacement of an issue body (flyingrobots/taskalisk#1).
#![cfg(unix)]

mod fake;

use fake::Fake;
use issue_dag_core::{Actor, ForgeWrite, IssueRef, Observed};
use issue_dag_gh::WriteFailure;
use serde_json::{Value, json};

fn state() -> Value {
    json!({
        "home": "o/r",
        "blocked_by": {},
        "issues": {
            "o/r#1": {"id": 1, "title": "t", "state": "open", "body": "old\r\nbody",
                      "author": "o", "association": "OWNER"}
        },
        "writer": {"login": "Dev", "type": "User"}
    })
}

fn one() -> IssueRef {
    IssueRef::parse("o/r#1").expect("a reference")
}

#[test]
fn the_writer_is_the_authenticated_account() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r");
    assert_eq!(
        forge.writer(),
        Observed::Value(Actor {
            login: "Dev".to_owned(),
            actor_type: "User".to_owned(),
        })
    );
    assert_eq!(fake.calls(), vec![vec!["api".to_owned(), "user".to_owned()]]);
    assert!(forge.failures().is_empty());
}

#[test]
fn a_writer_that_cannot_be_identified_is_unavailable_and_kept_as_a_failure() {
    let mut state = state();
    state["writer_fail"] = json!(true);
    let fake = Fake::new(&state);
    let forge = fake.forge("o/r");
    assert!(matches!(forge.writer(), Observed::Unavailable(_)));
    let failures = forge.failures();
    assert_eq!(failures.len(), 1);
    assert_eq!(failures[0].code(), "gh.command_failed");
}

#[test]
fn a_writer_answer_without_a_login_is_invalid() {
    let mut state = state();
    state["writer"] = json!({"type": "User"});
    let fake = Fake::new(&state);
    let forge = fake.forge("o/r");
    assert!(matches!(forge.writer(), Observed::Unavailable(_)));
    assert_eq!(forge.failures()[0].code(), "gh.response_invalid");
}

#[test]
fn the_body_is_replaced_with_one_patch_whose_input_is_the_json_body() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r");
    forge
        .replace_body(&one(), "new\r\nbody \u{2028} \"quoted\"")
        .expect("the write succeeds");
    assert_eq!(
        fake.calls(),
        vec![
            ["api", "-X", "PATCH", "repos/o/r/issues/1", "--input", "-"]
                .iter()
                .map(|s| (*s).to_owned())
                .collect::<Vec<_>>()
        ]
    );
    let state = fake.state();
    assert_eq!(
        state["issues"]["o/r#1"]["body"],
        json!("new\r\nbody \u{2028} \"quoted\"")
    );
    // The fake records the edit under the authenticated account.
    let editors = state["issues"]["o/r#1"]["editors"]
        .as_array()
        .expect("editors");
    assert_eq!(editors.last(), Some(&json!({"login": "Dev", "type": "User"})));
}

#[test]
fn a_failed_patch_is_a_write_failure_made_once() {
    let mut state = state();
    state["patch_fail"] = json!(true);
    let fake = Fake::new(&state);
    let forge = fake.forge("o/r");
    let failure: WriteFailure = forge.replace_body(&one(), "new").expect_err("it fails");
    assert_eq!(failure.source, "gh api -X PATCH repos/o/r/issues/1");
    assert!(failure.detail.contains("HTTP 502"), "{failure}");
    assert_eq!(WriteFailure::CODE, "gh.mutation_failed");
    assert_eq!(fake.calls().len(), 1, "never retried");
    assert_eq!(fake.state()["issues"]["o/r#1"]["body"], json!("old\r\nbody"));
}

#[test]
fn a_patch_whose_answer_is_lost_is_a_failure_even_though_it_applied() {
    let mut state = state();
    state["patch_lost"] = json!(true);
    let fake = Fake::new(&state);
    let forge = fake.forge("o/r");
    assert!(forge.replace_body(&one(), "new").is_err());
    assert_eq!(fake.calls().len(), 1);
    assert_eq!(fake.state()["issues"]["o/r#1"]["body"], json!("new"));
}
