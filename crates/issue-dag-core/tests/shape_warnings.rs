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

/// The graph of a run over the open home issues `bodies`, by number, each
/// written by the owner; the run must give a plan.
fn graph(bodies: &[(u32, String)]) -> Graph {
    let owner = Actor {
        login: "o".to_owned(),
        actor_type: "User".to_owned(),
    };
    let mut observations = Observations {
        home_open_issues: Some(Observed::Value(
            bodies
                .iter()
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
                state: IssueState::Open,
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

/// #62: `o/r#3` is blocked by `o/r#1` directly and through `o/r#2`, so the
/// edge `o/r#1 -> o/r#3` is redundant (G5). One warning names it: its
/// subject is the dependent, it concerns the prerequisite, and its detail is
/// the path that implies it.
#[test]
fn a_redundant_edge_gives_one_warning_naming_it_and_its_path() {
    let found = shape_warnings(&graph(&[
        (1, task(1, &[], "")),
        (2, task(2, &[1], "")),
        (3, task(3, &[1, 2], "")),
    ]));
    let redundant = of(&found, ShapeWarning::RedundantEdge);
    assert_eq!(redundant.len(), 1, "{found:?}");
    let warning = redundant[0];
    assert_eq!(warning.finding.subject, reference("o/r#3"));
    assert_eq!(warning.finding.concerns, Some(reference("o/r#1")));
    assert_eq!(warning.finding.severity(), Severity::Warning);
    assert_eq!(
        warning.detail,
        Detail::Path(vec![
            reference("o/r#1"),
            reference("o/r#2"),
            reference("o/r#3")
        ])
    );
}

/// #62: the same plan, reduced, gives no redundant-edge warning.
#[test]
fn the_reduced_plan_gives_no_redundant_edge_warning() {
    let found = shape_warnings(&graph(&[
        (1, task(1, &[], "")),
        (2, task(2, &[1], "")),
        (3, task(3, &[2], "")),
    ]));
    assert!(
        of(&found, ShapeWarning::RedundantEdge).is_empty(),
        "{found:?}"
    );
}

/// #62: the path is over the reduced graph, so it never uses another
/// redundant edge, and it is the shortest one.
#[test]
fn a_redundant_edge_s_path_is_the_shortest_through_the_reduced_graph() {
    // 1 -> 2 -> 3 -> 4, plus 1 -> 3, 1 -> 4 and 2 -> 4, all redundant.
    let found = shape_warnings(&graph(&[
        (1, task(1, &[], "")),
        (2, task(2, &[1], "")),
        (3, task(3, &[1, 2], "")),
        (4, task(4, &[1, 2, 3], "")),
    ]));
    let paths: Vec<(IssueRef, IssueRef, Detail)> = of(&found, ShapeWarning::RedundantEdge)
        .into_iter()
        .map(|f| {
            (
                f.finding.concerns.clone().expect("a prerequisite"),
                f.finding.subject.clone(),
                f.detail.clone(),
            )
        })
        .collect();
    let path =
        |ids: &[u32]| Detail::Path(ids.iter().map(|n| reference(&format!("o/r#{n}"))).collect());
    assert_eq!(
        paths,
        [
            (reference("o/r#1"), reference("o/r#3"), path(&[1, 2, 3])),
            (reference("o/r#1"), reference("o/r#4"), path(&[1, 2, 3, 4])),
            (reference("o/r#2"), reference("o/r#4"), path(&[2, 3, 4])),
        ]
    );
}
