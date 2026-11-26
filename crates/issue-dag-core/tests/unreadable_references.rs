//! Why a reference could not be read (flyingrobots/taskalisk#45).
//!
//! The observations a run reads today tell three causes apart, each with the
//! finding of its profile rule: outside the read scope (`profile.D3`), a pull
//! request (`profile.D4`) and transferred (`profile.D5`). Each gives exactly
//! one finding with its code. D3 and D5 give one to each document that writes
//! the reference, concerning it; D4 gives its finding to the pull request
//! itself (profile rule F5), and each open task that writes it in
//! `.blocked_by` receives `profile.X3` concerning it.
//!
//! The other three causes, owner, repository or issue number not found, are
//! not told apart: bundle rule OB8 records a reference that resolves to no
//! issue as one unavailable slot whose reason is free text, and profile rule
//! D10 makes the run incomplete, with no findings (F2). The last tests pin
//! that, so a change to it is deliberate.

use std::collections::{BTreeMap, BTreeSet};

use issue_dag_core::{
    Actor, Body, Finding, Issue, IssueRef, IssueState, Observations, Observed, Outcome, Parameters,
    ReadScope, RecordedForge, Repo, TRUST_POLICY, TrustParameters, plan,
};

fn reference(text: &str) -> IssueRef {
    IssueRef::parse(text).expect("a reference")
}

/// Home `o/r`, read scope the owner `o`, with these roots.
fn parameters(roots: &[&str]) -> Parameters {
    Parameters {
        home: Repo::parse("o/r").expect("a repository"),
        roots: roots.iter().map(|r| (*r).to_owned()).collect(),
        read_scope: ReadScope {
            owners: BTreeSet::from(["o".to_owned()]),
            repositories: BTreeSet::new(),
        },
        trust: TrustParameters {
            policy: TRUST_POLICY.to_owned(),
            logins: Vec::new(),
            codeowners: false,
        },
        capacities: BTreeMap::new(),
    }
}

fn observations() -> Observations {
    Observations {
        home_open_pull_requests: Some(Observed::Value(Vec::new())),
        ..Observations::default()
    }
}

/// Records the reference `key` as resolving to an open issue at `address`,
/// by the owner, with the body `text`.
fn record(observations: &mut Observations, key: &str, address: &str, text: &str, pull: bool) {
    let owner = Actor {
        login: "o".to_owned(),
        actor_type: "User".to_owned(),
    };
    observations.issues.insert(
        reference(key),
        Observed::Value(Issue {
            address: reference(address),
            pull_request: pull,
            state: IssueState::Open,
            state_reason: None,
            author: Some(owner.clone()),
            author_association: Some("OWNER".to_owned()),
        }),
    );
    observations.bodies.insert(
        reference(key),
        Observed::Value(Body {
            text: text.to_owned(),
            editors: vec![Some(owner)],
        }),
    );
}

/// An open issue at its own address.
fn issue(observations: &mut Observations, address: &str, text: &str) {
    record(observations, address, address, text, false);
}

/// The document of task `o/r#n`, blocked by `blocked_by`.
fn task(n: u32, blocked_by: &[&str]) -> String {
    format!(
        "```yaml\n.dag: issue-dag/2\n.id: o/r#{n}\n.kind: task\n.type: feature\n\
         .blocked_by: [{}]\n```\n",
        blocked_by.join(", ")
    )
}

/// The findings of an invalid run, as (subject, code, concerns).
fn findings(roots: &[&str], observations: &Observations) -> Vec<(String, String, Option<String>)> {
    let outcome = plan(&parameters(roots), &RecordedForge::new(observations));
    let Ok(Outcome::Invalid { findings, .. }) = outcome else {
        panic!("expected an invalid run, got {outcome:?}");
    };
    findings.iter().map(identity).collect()
}

fn identity(finding: &Finding) -> (String, String, Option<String>) {
    (
        finding.subject.to_string(),
        finding.code().to_string(),
        finding.concerns.as_ref().map(ToString::to_string),
    )
}

/// The findings with `code`.
fn with_code<'a>(
    found: &'a [(String, String, Option<String>)],
    code: &str,
) -> Vec<&'a (String, String, Option<String>)> {
    found.iter().filter(|(_, c, _)| c == code).collect()
}

fn found(subject: &str, code: &str, concerns: Option<&str>) -> (String, String, Option<String>) {
    (
        subject.to_owned(),
        code.to_owned(),
        concerns.map(ToOwned::to_owned),
    )
}

#[test]
fn outside_the_read_scope_gives_one_d3_finding_naming_the_reference_and_its_writer() {
    let mut obs = observations();
    issue(&mut obs, "o/r#1", &task(1, &["x/y#1"]));
    let all = findings(&["o/r#1"], &obs);
    assert_eq!(
        with_code(&all, "profile.D3"),
        [&found("o/r#1", "profile.D3", Some("x/y#1"))]
    );
}

#[test]
fn a_pull_request_gives_one_d4_finding_and_its_writer_an_x3_finding() {
    let mut obs = observations();
    issue(&mut obs, "o/r#1", &task(1, &["o/r#5"]));
    record(&mut obs, "o/r#5", "o/r#5", "", true);
    let all = findings(&["o/r#1"], &obs);
    assert_eq!(
        with_code(&all, "profile.D4"),
        [&found("o/r#5", "profile.D4", None)]
    );
    assert_eq!(
        with_code(&all, "profile.X3"),
        [&found("o/r#1", "profile.X3", Some("o/r#5"))]
    );
}

#[test]
fn a_transferred_issue_gives_one_d5_finding_naming_the_reference_and_its_writer() {
    let mut obs = observations();
    issue(&mut obs, "o/r#1", &task(1, &["o/r#6"]));
    record(&mut obs, "o/r#6", "o/r#9", "Moved here.", false);
    let all = findings(&["o/r#1"], &obs);
    assert_eq!(
        with_code(&all, "profile.D5"),
        [&found("o/r#1", "profile.D5", Some("o/r#6"))]
    );
}

/// Two tasks, `o/r#1` (the root) and `o/r#2`, both blocked by `target`.
fn two_writers(target: &str) -> Observations {
    let mut obs = observations();
    issue(&mut obs, "o/r#1", &task(1, &["o/r#2", target]));
    issue(&mut obs, "o/r#2", &task(2, &[target]));
    obs
}

#[test]
fn a_reference_outside_the_scope_written_by_two_documents_gives_each_a_d3_finding() {
    let all = findings(&["o/r#1"], &two_writers("x/y#1"));
    assert_eq!(
        with_code(&all, "profile.D3"),
        [
            &found("o/r#1", "profile.D3", Some("x/y#1")),
            &found("o/r#2", "profile.D3", Some("x/y#1")),
        ]
    );
}

#[test]
fn a_transferred_reference_written_by_two_documents_gives_each_a_d5_finding() {
    let mut obs = two_writers("o/r#6");
    record(&mut obs, "o/r#6", "o/r#9", "Moved here.", false);
    let all = findings(&["o/r#1"], &obs);
    assert_eq!(
        with_code(&all, "profile.D5"),
        [
            &found("o/r#1", "profile.D5", Some("o/r#6")),
            &found("o/r#2", "profile.D5", Some("o/r#6")),
        ]
    );
}

/// F5 gives D4 to the pull request, once; each task that writes it is named
/// by its own X3 finding.
#[test]
fn a_pull_request_written_by_two_documents_gives_each_an_x3_finding() {
    let mut obs = two_writers("o/r#5");
    record(&mut obs, "o/r#5", "o/r#5", "", true);
    let all = findings(&["o/r#1"], &obs);
    assert_eq!(
        with_code(&all, "profile.D4"),
        [&found("o/r#5", "profile.D4", None)]
    );
    assert_eq!(
        with_code(&all, "profile.X3"),
        [
            &found("o/r#1", "profile.X3", Some("o/r#5")),
            &found("o/r#2", "profile.X3", Some("o/r#5")),
        ]
    );
}

/// D10: a reference that resolves to no issue is unavailable (OB8), whatever
/// part of it was not found. The run is incomplete, carries the recorded
/// reason as it is, and has no findings. The reason is free text, so the core
/// does not read owner, repository or issue number out of it.
#[test]
fn a_reference_to_no_issue_makes_the_run_incomplete_whatever_was_not_found() {
    for reason in [
        "owner not found (HTTP 404)",
        "repository not found (HTTP 404)",
        "issue not found (HTTP 404)",
    ] {
        let mut obs = observations();
        issue(&mut obs, "o/r#1", &task(1, &["o/r#2"]));
        obs.issues
            .insert(reference("o/r#2"), Observed::Unavailable(reason.to_owned()));
        let outcome = plan(&parameters(&["o/r#1"]), &RecordedForge::new(&obs));
        assert_eq!(
            outcome,
            Ok(Outcome::Incomplete {
                unavailable: reason.to_owned()
            }),
            "{reason}"
        );
    }
}
