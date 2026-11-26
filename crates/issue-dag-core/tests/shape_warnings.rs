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

/// #47: `o/r#3` has no edge in or out while `o/r#1` and `o/r#2` are joined,
/// so `o/r#3`, and only it, is isolated. The run is still a plan: the
/// warning leaves it valid.
#[test]
fn an_isolated_open_task_gives_one_warning_naming_it() {
    let found = shape_warnings(&graph(&[
        (1, task(1, &[], "")),
        (2, task(2, &[1], "")),
        (3, task(3, &[], "")),
    ]));
    let isolated = of(&found, ShapeWarning::IsolatedTask);
    assert_eq!(isolated.len(), 1, "{found:?}");
    let warning = isolated[0];
    assert_eq!(warning.finding.subject, reference("o/r#3"));
    assert_eq!(warning.finding.concerns, None);
    assert_eq!(warning.finding.severity(), Severity::Warning);
    assert_eq!(warning.detail, Detail::None);
}

/// #47: the same task with one edge, in or out, draws no warning.
#[test]
fn the_same_task_with_one_edge_gives_no_isolated_task_warning() {
    // An edge in: 3 is blocked by 2. An edge out: 2 is blocked by 3.
    for (second, third) in [
        (task(2, &[1], ""), task(3, &[2], "")),
        (task(2, &[1, 3], ""), task(3, &[], "")),
    ] {
        let found = shape_warnings(&graph(&[(1, task(1, &[], "")), (2, second), (3, third)]));
        assert!(
            of(&found, ShapeWarning::IsolatedTask).is_empty(),
            "{found:?}"
        );
    }
}

/// #47: a plan of a single task draws no warning.
#[test]
fn a_plan_of_a_single_task_gives_no_isolated_task_warning() {
    let found = shape_warnings(&graph(&[(1, task(1, &[], ""))]));
    assert!(
        of(&found, ShapeWarning::IsolatedTask).is_empty(),
        "{found:?}"
    );
}
