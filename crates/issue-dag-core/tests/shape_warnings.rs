//! Plan-shape warnings (flyingrobots/taskalisk#42): Taskalisk's advisories on
//! the shape of a plan's graph. Each warning has a plan that produces it and
//! one that does not; every finding is a warning with a catalogued code.

use std::collections::{BTreeMap, BTreeSet};

use issue_dag_core::{
    Actor, Body, Detail, Graph, Issue, IssueRef, IssueState, Observations, Observed, Outcome,
    Parameters, ReadScope, RecordedForge, Repo, SHAPE_WARNINGS, Severity, ShapeFinding,
    ShapeWarning, TRUST_POLICY, TrustParameters, plan, shape_warnings,
};

fn reference(text: &str) -> IssueRef {
    IssueRef::parse(text).expect("a reference")
}

/// A task document for `o/r#<id>`, blocked by `blocked_by`, with `extra`
/// lines of frontmatter.
fn task(id: u32, blocked_by: &[u32], extra: &str) -> String {
    let refs: Vec<String> = blocked_by.iter().map(|n| format!("o/r#{n}")).collect();
    format!(
        "```yaml\n.dag: issue-dag/2\n.id: o/r#{id}\n.kind: task\n.type: feature\n\
         .blocked_by: [{}]\n{extra}```\n",
        refs.join(", ")
    )
}

/// A container document for `o/r#<id>` with `children`.
fn container(id: u32, children: &[u32]) -> String {
    let refs: Vec<String> = children.iter().map(|n| format!("o/r#{n}")).collect();
    format!(
        "```yaml\n.dag: issue-dag/2\n.id: o/r#{id}\n.kind: container\n.children: [{}]\n```\n",
        refs.join(", ")
    )
}

/// The graph of a run over the open home issues `bodies`, by number, each
/// written by the owner; the run must give a plan.
fn graph(bodies: &[(u32, String)]) -> Graph {
    graph_closing(bodies, &[])
}

/// As [`graph`], with the issues numbered in `closed` closed: they are not
/// seeds, and are read only when a document names them.
fn graph_closing(bodies: &[(u32, String)], closed: &[u32]) -> Graph {
    let owner = Actor {
        login: "o".to_owned(),
        actor_type: "User".to_owned(),
    };
    let mut observations = Observations {
        home_open_issues: Some(Observed::Value(
            bodies
                .iter()
                .filter(|(n, _)| !closed.contains(n))
                .map(|(n, _)| reference(&format!("o/r#{n}")))
                .collect(),
        )),
        home_open_pull_requests: Some(Observed::Value(Vec::new())),
        ..Observations::default()
    };
    for (n, text) in bodies {
        let address = reference(&format!("o/r#{n}"));
        observations.issues.insert(
            address.clone(),
            Observed::Value(Issue {
                address: address.clone(),
                pull_request: false,
                state: if closed.contains(n) {
                    IssueState::Closed
                } else {
                    IssueState::Open
                },
                state_reason: None,
                author: Some(owner.clone()),
                author_association: Some("OWNER".to_owned()),
            }),
        );
        observations.bodies.insert(
            address,
            Observed::Value(Body {
                text: text.clone(),
                editors: vec![Some(owner.clone())],
            }),
        );
    }
    let parameters = Parameters {
        home: Repo::parse("o/r").expect("a repository"),
        roots: Vec::new(),
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
    };
    match plan(&parameters, &RecordedForge::new(&observations)) {
        Ok(Outcome::Planned { graph, .. }) => graph,
        other => panic!("expected a plan, got {other:?}"),
    }
}

/// The warnings of `warning`'s code among `found`.
fn of(found: &[ShapeFinding], warning: ShapeWarning) -> Vec<&ShapeFinding> {
    found
        .iter()
        .filter(|f| f.finding.code() == warning.code())
        .collect()
}

#[test]
fn every_shape_warning_is_a_catalogued_warning() {
    for warning in SHAPE_WARNINGS {
        let code = issue_dag_core::Code::all()
            .find(|c| *c == warning.code())
            .unwrap_or_else(|| panic!("{} is not catalogued", warning.code()));
        assert_eq!(code.severity(), Severity::Warning, "{}", warning.code());
        assert!(
            warning.code().starts_with("taskalisk."),
            "{}",
            warning.code()
        );
    }
}

/// #63: containers with no child and with one child each give the warning,
/// naming the container; one with two children does not. The run is still
/// a plan: the warning leaves it valid.
#[test]
fn a_container_with_fewer_than_two_children_gives_one_warning() {
    let found = shape_warnings(&graph(&[
        (1, task(1, &[], "")),
        (2, task(2, &[], "")),
        (7, container(7, &[])),
        (8, container(8, &[1])),
        (9, container(9, &[1, 2])),
    ]));
    let small = of(&found, ShapeWarning::SmallContainer);
    let subjects: Vec<&IssueRef> = small.iter().map(|f| &f.finding.subject).collect();
    assert_eq!(subjects, [&reference("o/r#7"), &reference("o/r#8")]);
    for warning in small {
        assert_eq!(warning.finding.concerns, None);
        assert_eq!(warning.finding.severity(), Severity::Warning);
        assert_eq!(warning.detail, Detail::None);
    }
}

/// #63: a child named twice counts once.
#[test]
fn a_child_named_twice_counts_once() {
    let found = shape_warnings(&graph(&[(1, task(1, &[], "")), (8, container(8, &[1, 1]))]));
    let small = of(&found, ShapeWarning::SmallContainer);
    assert_eq!(small.len(), 1, "{found:?}");
    assert_eq!(small[0].finding.subject, reference("o/r#8"));
}

/// #63: only an open container is warned about. A closed one with a single
/// child, read because an open container names it, draws none.
#[test]
fn a_closed_container_gives_no_warning() {
    let found = shape_warnings(&graph_closing(
        &[
            (1, task(1, &[], "")),
            (9, container(9, &[1])),
            (10, container(10, &[1, 9])),
        ],
        &[9],
    ));
    assert!(
        of(&found, ShapeWarning::SmallContainer).is_empty(),
        "{found:?}"
    );
}
