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
//! told apart by the cause bundle rule OB17 records beside the free-text
//! reason of the unavailable slot (flyingrobots/taskalisk#126). Profile rule
//! D10 keeps the run incomplete whatever the cause, with no findings (F2),
//! and the run reports the cause of the slot it reports (OB16) with the code
//! of its rule: `profile.D11`, `profile.D12` or `profile.D13`. A slot that
//! records no cause is reported as before, with no cause; the core never
//! reads a cause out of the reason.

use std::collections::{BTreeMap, BTreeSet};

use issue_dag_core::{
    Actor, Body, CODES, Finding, Issue, IssueRef, IssueState, NotFound, Observations, Observed,
    Outcome, Parameters, ReadScope, RecordedForge, Repo, Severity, TRUST_POLICY, TrustParameters,
    plan,
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

/// F5: findings with one identity are one finding, so a task that names the
/// same unknown prerequisite twice receives one X3 finding, and the report
/// lists the unknown prerequisite once (difference 27: the Python gives one
/// per occurrence).
#[test]
fn an_unknown_prerequisite_named_twice_gives_one_x3_finding() {
    let mut obs = observations();
    issue(&mut obs, "o/r#1", &task(1, &["o/r#5", "o/r#5"]));
    record(&mut obs, "o/r#5", "o/r#5", "", true);
    let outcome = plan(&parameters(&["o/r#1"]), &RecordedForge::new(&obs));
    let Ok(Outcome::Invalid {
        findings, unknown, ..
    }) = outcome
    else {
        panic!("expected an invalid run, got {outcome:?}");
    };
    let x3: Vec<_> = findings
        .iter()
        .map(identity)
        .filter(|(_, code, _)| code == "profile.X3")
        .collect();
    assert_eq!(x3, [found("o/r#1", "profile.X3", Some("o/r#5"))]);
    assert_eq!(unknown.len(), 1, "{unknown:?}");
}

/// Records `key` as resolving to no issue, for `reason`, with `cause` when
/// the slot records one (OB17).
fn not_found(observations: &mut Observations, key: &str, reason: &str, cause: Option<NotFound>) {
    observations
        .issues
        .insert(reference(key), Observed::Unavailable(reason.to_owned()));
    if let Some(cause) = cause {
        observations.not_found.insert(reference(key), cause);
    }
}

/// The incomplete run's reason and cause, or a panic.
fn incomplete(roots: &[&str], observations: &Observations) -> (String, Option<NotFound>) {
    let outcome = plan(&parameters(roots), &RecordedForge::new(observations));
    let Ok(Outcome::Incomplete { unavailable, cause }) = outcome else {
        panic!("expected an incomplete run, got {outcome:?}");
    };
    (unavailable, cause)
}

/// The three references of the cases: an owner, a repository and an issue
/// number that no lookup found. `gone` is in the read scope.
const OWNER: &str = "gone/r#2";
const REPOSITORY: &str = "o/gone#2";
const NUMBER: &str = "o/r#2";

fn scoped(roots: &[&str]) -> Parameters {
    let mut p = parameters(roots);
    p.read_scope.owners.insert("gone".to_owned());
    p
}

fn incomplete_in_scope(roots: &[&str], observations: &Observations) -> (String, Option<NotFound>) {
    let outcome = plan(&scoped(roots), &RecordedForge::new(observations));
    let Ok(Outcome::Incomplete { unavailable, cause }) = outcome else {
        panic!("expected an incomplete run, got {outcome:?}");
    };
    (unavailable, cause)
}

/// D10 to D13: each cause keeps the run incomplete, and the run reports it
/// with the reason, under the code of its rule.
#[test]
fn a_reference_not_found_reports_its_cause_with_its_code() {
    for (target, cause, code) in [
        (OWNER, NotFound::Owner, "profile.D11"),
        (REPOSITORY, NotFound::Repository, "profile.D12"),
        (NUMBER, NotFound::Number, "profile.D13"),
    ] {
        let mut obs = observations();
        issue(&mut obs, "o/r#1", &task(1, &[target]));
        not_found(&mut obs, target, "HTTP 404", Some(cause));
        let (reason, reported) = incomplete_in_scope(&["o/r#1"], &obs);
        assert_eq!(reason, "HTTP 404", "{target}");
        assert_eq!(reported, Some(cause), "{target}");
        assert_eq!(cause.code().as_str(), code);
    }
}

/// D10 with no cause: the run is incomplete, carries the recorded reason as
/// it is, and reports no cause. The reason is free text, so the core does
/// not read owner, repository or issue number out of it.
#[test]
fn a_reference_not_found_with_no_cause_reports_none_whatever_the_reason_says() {
    for reason in [
        "owner not found (HTTP 404)",
        "repository not found (HTTP 404)",
        "issue not found (HTTP 404)",
    ] {
        let mut obs = observations();
        issue(&mut obs, "o/r#1", &task(1, &["o/r#2"]));
        not_found(&mut obs, "o/r#2", reason, None);
        assert_eq!(
            incomplete(&["o/r#1"], &obs),
            (reason.to_owned(), None),
            "{reason}"
        );
    }
}

/// OB17: the cause is the recorded one, even when the reason says another.
#[test]
fn the_cause_is_the_recorded_one_not_the_one_the_reason_names() {
    let mut obs = observations();
    issue(&mut obs, "o/r#1", &task(1, &["o/r#2"]));
    not_found(
        &mut obs,
        "o/r#2",
        "owner not found (HTTP 404)",
        Some(NotFound::Number),
    );
    assert_eq!(
        incomplete(&["o/r#1"], &obs),
        (
            "owner not found (HTTP 404)".to_owned(),
            Some(NotFound::Number)
        )
    );
}

/// D10 makes no finding of a cause, so a reference two documents name is
/// reported once, as the run's cause, and neither document is invalid.
#[test]
fn a_reference_not_found_named_by_two_documents_is_one_cause_and_no_finding() {
    let mut obs = two_writers(REPOSITORY);
    not_found(&mut obs, REPOSITORY, "HTTP 404", Some(NotFound::Repository));
    assert_eq!(
        incomplete(&["o/r#1"], &obs),
        ("HTTP 404".to_owned(), Some(NotFound::Repository))
    );
}

/// Two roots, `o/r#2` blocked by [`REPOSITORY`] and `o/r#3` by [`OWNER`],
/// recorded with these reasons and causes, in both orders of the roots.
fn two_not_found(
    repository: (&str, Option<NotFound>),
    owner: (&str, Option<NotFound>),
) -> [(String, Option<NotFound>); 2] {
    let mut obs = observations();
    issue(&mut obs, "o/r#2", &task(2, &[REPOSITORY]));
    issue(&mut obs, "o/r#3", &task(3, &[OWNER]));
    not_found(&mut obs, REPOSITORY, repository.0, repository.1);
    not_found(&mut obs, OWNER, owner.0, owner.1);
    [
        incomplete_in_scope(&["o/r#2", "o/r#3"], &obs),
        incomplete_in_scope(&["o/r#3", "o/r#2"], &obs),
    ]
}

/// OB16: of slots with the least reason, the least cause, by the bytes of
/// its value: `owner` before `repository`.
#[test]
fn of_two_causes_with_one_reason_the_least_is_reported() {
    let expected = ("HTTP 404".to_owned(), Some(NotFound::Owner));
    assert_eq!(
        two_not_found(
            ("HTTP 404", Some(NotFound::Repository)),
            ("HTTP 404", Some(NotFound::Owner))
        ),
        [expected.clone(), expected]
    );
}

/// OB16: a slot with no cause comes before one with a cause.
#[test]
fn a_slot_with_no_cause_comes_before_one_with_a_cause() {
    let expected = ("HTTP 404".to_owned(), None);
    assert_eq!(
        two_not_found(("HTTP 404", None), ("HTTP 404", Some(NotFound::Owner))),
        [expected.clone(), expected]
    );
}

/// OB16: the reason decides first; the cause is that of the least reason.
#[test]
fn the_cause_reported_is_that_of_the_least_reason() {
    let expected = ("HTTP 404".to_owned(), Some(NotFound::Repository));
    assert_eq!(
        two_not_found(
            ("HTTP 404", Some(NotFound::Repository)),
            ("timeout", Some(NotFound::Owner))
        ),
        [expected.clone(), expected]
    );
}

/// OB17: the three values of `not_found`, and nothing else, are causes; in
/// the order OB16 compares them, the bytes of their values.
#[test]
fn a_cause_is_one_of_three_values() {
    assert_eq!(NotFound::parse("owner"), Some(NotFound::Owner));
    assert_eq!(NotFound::parse("repository"), Some(NotFound::Repository));
    assert_eq!(NotFound::parse("number"), Some(NotFound::Number));
    for other in ["", "Owner", "team", "issue", "number "] {
        assert_eq!(NotFound::parse(other), None, "{other:?}");
    }
    let mut by_value = NotFound::ALL;
    by_value.sort_by_key(|c| c.as_str());
    let mut by_order = NotFound::ALL;
    by_order.sort();
    assert_eq!(by_value, by_order);
    for cause in NotFound::ALL {
        assert_eq!(NotFound::parse(cause.as_str()), Some(cause));
    }
}

/// The three codes are catalogued, as errors, once each, named after the
/// labels of their rules.
#[test]
fn the_three_codes_are_catalogued() {
    let codes: Vec<(&str, Severity)> = NotFound::ALL
        .iter()
        .map(|c| (c.code().as_str(), c.code().severity()))
        .collect();
    for (code, severity) in &codes {
        assert_eq!(*severity, Severity::Error, "{code}");
        assert_eq!(CODES.iter().filter(|(c, _)| c == code).count(), 1, "{code}");
    }
    let mut names: Vec<&str> = codes.iter().map(|(c, _)| *c).collect();
    names.sort_unstable();
    assert_eq!(names, ["profile.D11", "profile.D12", "profile.D13"]);
    assert_eq!(NotFound::Owner.label(), "D11");
    assert_eq!(NotFound::Repository.label(), "D12");
    assert_eq!(NotFound::Number.label(), "D13");
}
