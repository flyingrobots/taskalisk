//! Violations that appear only when documents are read together, and what
//! an invalid run reports (flyingrobots/taskalisk#44).
//!
//! Each cross-document rule of `issue-dag-planning/2` has a run that keeps
//! it and one that breaks it: own address (X1), no container prerequisite
//! (X2), unknown prerequisite (X3) and cycles (G4). A finding is identified
//! by its subject, its rule and the reference it concerns (F5): a broken X2
//! or X3 gives the task one finding concerning the prerequisite, and every
//! node G4 reports receives its own G4 finding, so a three-issue cycle names
//! all three issues.
//!
//! An invalid run reports what discovery read (decision D13), a cycle or an
//! unknown prerequisite included, though rule F3 lets it withhold its graph:
//! the containers with their children, the unmodeled, untrusted and opaque
//! issues, the untrusted pull requests and the not-planned prerequisites.

use std::collections::{BTreeMap, BTreeSet};

use issue_dag_core::{
    Actor, Body, Discovered, Edge, Finding, Issue, IssueRef, IssueState, Observations, Observed,
    Outcome, Parameters, PullRequest, ReadScope, RecordedForge, Repo, TRUST_POLICY,
    TrustParameters, plan,
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

fn actor(login: &str) -> Actor {
    Actor {
        login: login.to_owned(),
        actor_type: "User".to_owned(),
    }
}

/// Records the issue `address` in `state`, by `login` (the owner `o` or a
/// stranger), with the body `text`.
fn record(
    observations: &mut Observations,
    address: &str,
    state: (IssueState, Option<&str>),
    login: &str,
    text: &str,
) {
    let association = if login == "o" { "OWNER" } else { "NONE" };
    observations.issues.insert(
        reference(address),
        Observed::Value(Issue {
            address: reference(address),
            pull_request: false,
            state: state.0,
            state_reason: state.1.map(str::to_owned),
            author: Some(actor(login)),
            author_association: Some(association.to_owned()),
        }),
    );
    observations.bodies.insert(
        reference(address),
        Observed::Value(Body {
            text: text.to_owned(),
            editors: vec![Some(actor(login))],
        }),
    );
}

const OPEN: (IssueState, Option<&str>) = (IssueState::Open, None);
const NOT_PLANNED: (IssueState, Option<&str>) = (IssueState::Closed, Some("not_planned"));

/// Records an open issue by the owner.
fn owned(observations: &mut Observations, address: &str, text: &str) {
    record(observations, address, OPEN, "o", text);
}

/// A document of `.kind` `kind` with the `.id` `id`, whose `key` lists
/// `refs`.
fn document(id: &str, kind: &str, key: &str, refs: &[&str]) -> String {
    let task_type = if kind == "task" {
        ".type: feature\n"
    } else {
        ""
    };
    format!(
        "```yaml\n.dag: issue-dag/2\n.id: {id}\n.kind: {kind}\n{task_type}{key}: [{}]\n```\n",
        refs.join(", ")
    )
}

fn task(id: &str, blocked_by: &[&str]) -> String {
    document(id, "task", ".blocked_by", blocked_by)
}

fn container(id: &str, children: &[&str]) -> String {
    document(id, "container", ".children", children)
}

fn run(roots: &[&str], observations: &Observations) -> Outcome {
    plan(&parameters(roots), &RecordedForge::new(observations)).expect("recorded")
}

/// The findings of a run that is not rejected or incomplete, as
/// (subject, label, concerns).
fn identities(outcome: &Outcome) -> BTreeSet<(String, &'static str, Option<String>)> {
    let findings: &BTreeSet<Finding> = match outcome {
        Outcome::Invalid { findings, .. } | Outcome::Planned { findings, .. } => findings,
        other => panic!("expected findings, got {other:?}"),
    };
    findings
        .iter()
        .map(|f| {
            (
                f.subject.to_string(),
                f.label(),
                f.concerns.as_ref().map(ToString::to_string),
            )
        })
        .collect()
}

fn finding(subject: &str, label: &'static str, concerns: Option<&str>) -> (String, &'static str, Option<String>) {
    (subject.to_owned(), label, concerns.map(str::to_owned))
}

fn is_planned(outcome: &Outcome) -> bool {
    matches!(outcome, Outcome::Planned { .. })
}

// X1. Own address.

#[test]
fn x1_a_document_at_its_own_address_has_no_finding() {
    let mut o = observations();
    owned(&mut o, "o/r#1", &task("o/r#1", &[]));
    let outcome = run(&["o/r#1"], &o);
    assert!(is_planned(&outcome), "got {outcome:?}");
    assert!(identities(&outcome).is_empty());
}

#[test]
fn x1_a_document_copied_from_another_issue_is_a_violation() {
    let mut o = observations();
    owned(&mut o, "o/r#1", &task("o/r#7", &[]));
    let outcome = run(&["o/r#1"], &o);
    assert!(matches!(outcome, Outcome::Invalid { .. }), "got {outcome:?}");
    assert_eq!(
        identities(&outcome),
        BTreeSet::from([finding("o/r#1", "X1", None)])
    );
}

// X2. No container prerequisite.

#[test]
fn x2_a_task_waiting_on_a_task_has_no_finding() {
    let mut o = observations();
    owned(&mut o, "o/r#1", &task("o/r#1", &["o/r#2"]));
    owned(&mut o, "o/r#2", &task("o/r#2", &[]));
    let outcome = run(&["o/r#1"], &o);
    assert!(is_planned(&outcome), "got {outcome:?}");
    assert!(identities(&outcome).is_empty());
}

#[test]
fn x2_a_task_waiting_on_a_container_is_a_violation_and_makes_no_edge() {
    let mut o = observations();
    owned(&mut o, "o/r#1", &task("o/r#1", &["o/r#9"]));
    owned(&mut o, "o/r#9", &container("o/r#9", &[]));
    let outcome = run(&["o/r#1"], &o);
    let Outcome::Invalid {
        graph: Some(graph), ..
    } = &outcome
    else {
        panic!("expected an invalid run with its graph, got {outcome:?}");
    };
    assert!(graph.edges.is_empty());
    assert_eq!(
        identities(&outcome),
        BTreeSet::from([finding("o/r#1", "X2", Some("o/r#9"))])
    );
}

// X3. Unknown prerequisite.

#[test]
fn x3_a_task_waiting_on_a_node_has_no_finding() {
    let mut o = observations();
    owned(&mut o, "o/r#1", &task("o/r#1", &["o/r#2"]));
    owned(&mut o, "o/r#2", "A plain body.");
    let outcome = run(&["o/r#1"], &o);
    assert!(is_planned(&outcome), "got {outcome:?}");
    assert!(identities(&outcome).is_empty());
}

#[test]
fn x3_a_task_waiting_on_a_pull_request_names_an_unknown_prerequisite() {
    let mut o = observations();
    owned(&mut o, "o/r#1", &task("o/r#1", &["o/r#2"]));
    owned(&mut o, "o/r#2", "A pull request.");
    if let Some(Observed::Value(issue)) = o.issues.get_mut(&reference("o/r#2")) {
        issue.pull_request = true;
    }
    let outcome = run(&["o/r#1"], &o);
    let Outcome::Invalid { graph, unknown, .. } = &outcome else {
        panic!("expected an invalid run, got {outcome:?}");
    };
    assert_eq!(*graph, None, "F3: an unresolved graph is not reported");
    assert_eq!(
        *unknown,
        vec![Edge {
            from: reference("o/r#2"),
            to: reference("o/r#1"),
        }]
    );
    assert_eq!(
        identities(&outcome),
        BTreeSet::from([
            finding("o/r#1", "X3", Some("o/r#2")),
            finding("o/r#2", "D4", None),
        ])
    );
}

// G4. Cycles.

#[test]
fn g4_a_chain_of_three_has_no_finding() {
    let mut o = observations();
    owned(&mut o, "o/r#1", &task("o/r#1", &["o/r#3"]));
    owned(&mut o, "o/r#2", &task("o/r#2", &["o/r#1"]));
    owned(&mut o, "o/r#3", &task("o/r#3", &[]));
    let outcome = run(&["o/r#2"], &o);
    assert!(is_planned(&outcome), "got {outcome:?}");
    assert!(identities(&outcome).is_empty());
}

#[test]
fn g4_a_three_issue_cycle_names_every_issue_on_it() {
    let mut o = observations();
    owned(&mut o, "o/r#1", &task("o/r#1", &["o/r#3"]));
    owned(&mut o, "o/r#2", &task("o/r#2", &["o/r#1"]));
    owned(&mut o, "o/r#3", &task("o/r#3", &["o/r#2"]));
    let outcome = run(&["o/r#2"], &o);
    let Outcome::Invalid { graph, .. } = &outcome else {
        panic!("expected an invalid run, got {outcome:?}");
    };
    assert_eq!(*graph, None, "F3: a cyclic graph is not reported");
    assert_eq!(
        identities(&outcome),
        BTreeSet::from([
            finding("o/r#1", "G4", None),
            finding("o/r#2", "G4", None),
            finding("o/r#3", "G4", None),
        ])
    );
}

// Decision D13: an invalid run reports its discovery.

/// A run that reads every kind of thing discovery lists. The root
/// container o/r#9 names the container o/r#8, the tasks o/r#1 and o/r#2,
/// the plain o/r#5 and the stranger's o/r#6; o/r#8 names o/r#3. o/r#1
/// waits on o/r#5 and on o/r#4, closed as not planned; a stranger's pull
/// request, number 20, closes o/r#1. `tail` is o/r#2's `.blocked_by`.
fn everything(tail: &[&str]) -> Observations {
    let mut o = observations();
    owned(
        &mut o,
        "o/r#9",
        &container("o/r#9", &["o/r#8", "o/r#1", "o/r#2", "o/r#5", "o/r#6"]),
    );
    owned(&mut o, "o/r#8", &container("o/r#8", &["o/r#3"]));
    owned(&mut o, "o/r#1", &task("o/r#1", &["o/r#5", "o/r#4"]));
    owned(&mut o, "o/r#2", &task("o/r#2", tail));
    owned(&mut o, "o/r#3", &task("o/r#3", &["o/r#2"]));
    record(&mut o, "o/r#4", NOT_PLANNED, "o", &task("o/r#4", &[]));
    owned(&mut o, "o/r#5", "A plain body.");
    record(&mut o, "o/r#6", OPEN, "stranger", &task("o/r#6", &[]));
    o.home_open_pull_requests = Some(Observed::Value(vec![PullRequest {
        number: 20,
        repository: Repo::parse("o/r").expect("a repository"),
        author: Some(actor("stranger")),
        draft: Observed::Value(false),
        closes: vec![reference("o/r#1")],
        cross_repository: Some(false),
        head_repository: Some(Repo::parse("o/r").expect("a repository")),
    }]));
    for login in ["o", "stranger"] {
        o.permissions
            .entry(Repo::parse("o/r").expect("a repository"))
            .or_default()
            .insert(login.to_owned(), Observed::Value(None));
    }
    o
}

/// What `everything` reads, whatever o/r#2 waits on.
fn everything_discovered() -> Discovered {
    let refs = |texts: &[&str]| -> Vec<IssueRef> { texts.iter().map(|t| reference(t)).collect() };
    Discovered {
        visit_order: refs(&[
            "o/r#9", "o/r#8", "o/r#1", "o/r#2", "o/r#5", "o/r#6", "o/r#3", "o/r#4",
        ]),
        containers: BTreeMap::from([
            (
                reference("o/r#9"),
                refs(&["o/r#8", "o/r#1", "o/r#2", "o/r#5", "o/r#6"]),
            ),
            (reference("o/r#8"), refs(&["o/r#3"])),
        ]),
        unmodeled: BTreeSet::new(),
        untrusted: BTreeSet::from([reference("o/r#6")]),
        untrusted_pull_request_order: vec![20],
        opaque: BTreeMap::new(),
        not_planned_order: vec![Edge {
            from: reference("o/r#4"),
            to: reference("o/r#1"),
        }],
    }
}

/// The opaque nodes `everything` reads, as (id, untrusted, named by).
fn opaque(discovered: &Discovered) -> Vec<(String, bool, Vec<String>)> {
    discovered
        .opaque
        .iter()
        .map(|(id, node)| {
            (
                id.to_string(),
                node.untrusted,
                node.named_by.iter().map(ToString::to_string).collect(),
            )
        })
        .collect()
}

fn without_opaque(mut discovered: Discovered) -> Discovered {
    discovered.opaque.clear();
    discovered
}

fn everything_opaque() -> Vec<(String, bool, Vec<String>)> {
    vec![
        (
            "o/r#5".to_owned(),
            false,
            vec!["o/r#9".to_owned(), "o/r#1".to_owned()],
        ),
        ("o/r#6".to_owned(), true, vec!["o/r#9".to_owned()]),
    ]
}

#[test]
fn d13_a_planned_run_and_its_discovery_agree() {
    let outcome = run(&["o/r#9"], &everything(&[]));
    let Outcome::Planned { graph, .. } = &outcome else {
        panic!("expected a plan, got {outcome:?}");
    };
    let discovered = graph.discovered();
    assert_eq!(opaque(&discovered), everything_opaque());
    assert_eq!(without_opaque(discovered), everything_discovered());
}

#[test]
fn d13_a_cyclic_run_reports_its_discovery() {
    // o/r#2 waits on o/r#3, which waits on o/r#2.
    let outcome = run(&["o/r#9"], &everything(&["o/r#3"]));
    let Outcome::Invalid {
        graph, discovered, ..
    } = &outcome
    else {
        panic!("expected an invalid run, got {outcome:?}");
    };
    assert_eq!(*graph, None);
    assert_eq!(opaque(discovered), everything_opaque());
    assert_eq!(without_opaque(discovered.clone()), everything_discovered());
}

#[test]
fn d13_a_run_with_an_unknown_prerequisite_reports_its_discovery() {
    // o/r#2 waits on the container o/r#8 (X2) and on x/y#1, outside the
    // read scope (D3, X3).
    let outcome = run(&["o/r#9"], &everything(&["o/r#8", "x/y#1"]));
    let Outcome::Invalid {
        graph, discovered, ..
    } = &outcome
    else {
        panic!("expected an invalid run, got {outcome:?}");
    };
    assert_eq!(*graph, None);
    let mut want = everything_discovered();
    want.visit_order.push(reference("x/y#1"));
    assert_eq!(opaque(discovered), everything_opaque());
    assert_eq!(without_opaque(discovered.clone()), want);
    assert_eq!(
        identities(&outcome),
        BTreeSet::from([
            finding("o/r#2", "D3", Some("x/y#1")),
            finding("o/r#2", "X2", Some("o/r#8")),
            finding("o/r#2", "X3", Some("x/y#1")),
        ])
    );
}

#[test]
fn d13_an_invalid_run_with_its_graph_reports_the_same_discovery() {
    // A copied document (X1) leaves the graph reportable (F3).
    let mut o = everything(&[]);
    owned(&mut o, "o/r#2", &task("o/r#7", &[]));
    let outcome = run(&["o/r#9"], &o);
    let Outcome::Invalid {
        graph: Some(graph),
        discovered,
        ..
    } = &outcome
    else {
        panic!("expected an invalid run with its graph, got {outcome:?}");
    };
    assert_eq!(*discovered, graph.discovered());
}
