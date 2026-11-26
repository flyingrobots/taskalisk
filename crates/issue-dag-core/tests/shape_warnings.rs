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
    match run(bodies, closed) {
        Outcome::Planned { graph, .. } => graph,
        other => panic!("expected a plan, got {other:?}"),
    }
}

/// The outcome of a run over `bodies`, as for [`graph_closing`], whatever it
/// is.
fn run(bodies: &[(u32, String)], closed: &[u32]) -> Outcome {
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
    plan(&parameters, &RecordedForge::new(&observations)).expect("every observation is recorded")
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

/// The detail of a redundant-edge warning: the node it is implied via.
fn via(warning: &ShapeFinding) -> &IssueRef {
    match &warning.detail {
        Some(Detail::ImpliedVia(node)) => node,
        other => panic!("not a redundant edge's detail: {other:?}"),
    }
}

/// The redundant-edge warnings as `(prerequisite, dependent, implied via)`,
/// in the order given.
fn redundant(found: &[ShapeFinding]) -> Vec<(IssueRef, IssueRef, IssueRef)> {
    of(found, ShapeWarning::RedundantEdge)
        .into_iter()
        .map(|f| {
            (
                f.finding.concerns.clone().expect("a prerequisite"),
                f.finding.subject.clone(),
                via(f).clone(),
            )
        })
        .collect()
}

/// `count` open tasks numbered from 1, each blocked by the tasks `edges`
/// name for it, as `(prerequisite, dependent)`.
fn tasks(count: u32, edges: &[(u32, u32)]) -> Graph {
    let bodies: Vec<(u32, String)> = (1..=count)
        .map(|id| {
            let prerequisites: Vec<u32> = edges
                .iter()
                .filter(|(_, to)| *to == id)
                .map(|(from, _)| *from)
                .collect();
            (id, task(id, &prerequisites, ""))
        })
        .collect();
    graph(&bodies)
}

fn r(n: u32) -> IssueRef {
    reference(&format!("o/r#{n}"))
}

/// #62: `o/r#3` is blocked by `o/r#1` directly and through `o/r#2`, so the
/// edge `o/r#1 -> o/r#3` is redundant (G5). One warning names it: its
/// subject is the dependent, it concerns the prerequisite, and its detail is
/// the node it is implied via.
#[test]
fn a_redundant_edge_gives_one_warning_naming_it_and_its_implied_via() {
    let found = shape_warnings(&tasks(3, &[(1, 2), (2, 3), (1, 3)]));
    let warnings = of(&found, ShapeWarning::RedundantEdge);
    assert_eq!(warnings.len(), 1, "{found:?}");
    let warning = warnings[0];
    assert_eq!(warning.finding.subject, r(3));
    assert_eq!(warning.finding.concerns, Some(r(1)));
    assert_eq!(warning.finding.severity(), Severity::Warning);
    assert_eq!(warning.detail, Some(Detail::ImpliedVia(r(2))));
}

/// #62: the same plan, reduced, gives no redundant-edge warning.
#[test]
fn the_reduced_plan_gives_no_redundant_edge_warning() {
    let found = shape_warnings(&tasks(3, &[(1, 2), (2, 3)]));
    assert!(
        of(&found, ShapeWarning::RedundantEdge).is_empty(),
        "{found:?}"
    );
}

/// #62: a diamond, 1 -> 2 -> 4 and 1 -> 3 -> 4, with 1 -> 4: both 2 and 3
/// imply the edge, and the first child of 1 in reference text order is 2,
/// as the Python compiler's `implied_via` picks it.
#[test]
fn implied_via_is_the_first_child_that_reaches_the_dependent() {
    let found = shape_warnings(&tasks(4, &[(1, 2), (2, 4), (1, 3), (3, 4), (1, 4)]));
    assert_eq!(redundant(&found), [(r(1), r(4), r(2))]);
}

/// #62: the children are taken in the text order of their references, as
/// the Python compiler sorts its ids: `o/r#10` comes before `o/r#2`, and a
/// child joined by an edge that is itself redundant still counts.
#[test]
fn implied_via_takes_children_in_reference_text_order() {
    // 1 -> 2 -> 10 -> 11, with 1 -> 10 and 1 -> 11 both redundant. For
    // 1 -> 11, the children of 1 are o/r#10 and o/r#2; o/r#10 comes first.
    let found = shape_warnings(&tasks(11, &[(1, 2), (2, 10), (10, 11), (1, 10), (1, 11)]));
    assert_eq!(
        redundant(&found),
        [(r(1), r(10), r(2)), (r(1), r(11), r(10))]
    );
}

/// #62: the warnings sort by their findings (subject first), not by edge:
/// the edge 1 -> 5 comes before 2 -> 4, but its warning, whose subject is
/// o/r#5, comes after that of 2 -> 4, whose subject is o/r#4.
#[test]
fn redundant_edge_warnings_sort_by_subject_not_by_edge() {
    let found = shape_warnings(&tasks(6, &[(1, 3), (3, 5), (1, 5), (2, 6), (6, 4), (2, 4)]));
    assert_eq!(redundant(&found), [(r(2), r(4), r(6)), (r(1), r(5), r(3))]);
}

/// The reviewer's graph (#124): a chain of 5,000 tasks, each also blocked by
/// o/r#1, so 4,998 edges are redundant. Each is implied via o/r#2 (for a
/// dependent up to o/r#10) or o/r#10 (beyond), the first child of o/r#1 in
/// text order that reaches it.
fn chain_with_a_hub() -> Graph {
    let mut edges: Vec<(u32, u32)> = (1..5_000).map(|n| (n, n + 1)).collect();
    edges.extend((3..=5_000).map(|n| (1, n)));
    tasks(5_000, &edges)
}

fn check_chain_with_a_hub(found: &[ShapeFinding]) {
    let found = redundant(found);
    assert_eq!(found.len(), 4_998);
    for (from, to, through) in found {
        assert_eq!(from, r(1));
        let expected = if to.number() <= 10 { r(2) } else { r(10) };
        assert_eq!(through, expected, "{to}");
    }
}

#[test]
fn a_chain_with_a_hub_gives_one_warning_per_redundant_edge() {
    check_chain_with_a_hub(&shape_warnings(&chain_with_a_hub()));
}

#[test]
#[ignore = "wall-clock bound; run with --release --ignored"]
fn perf_redundant_edge_warnings_of_a_chain_with_a_hub_take_under_a_second() {
    let graph = chain_with_a_hub();
    let start = std::time::Instant::now();
    let found = shape_warnings(&graph);
    let took = start.elapsed();
    assert!(took < std::time::Duration::from_secs(1), "took {took:?}");
    check_chain_with_a_hub(&found);
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
        assert_eq!(warning.detail, None);
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

/// #63: a reference to the container itself is not a child. Container
/// o/r#8 writes `.children: [o/r#8, o/r#1]`: the self reference makes it
/// invalid (V7), but the run still reports its graph, where o/r#8 groups
/// one issue and gets the warning.
#[test]
fn a_container_s_reference_to_itself_is_not_a_child() {
    let outcome = run(&[(1, task(1, &[], "")), (8, container(8, &[8, 1]))], &[]);
    let Outcome::Invalid {
        graph: Some(graph), ..
    } = outcome
    else {
        panic!("expected an invalid run with its graph, got {outcome:?}");
    };
    let found = shape_warnings(&graph);
    let small = of(&found, ShapeWarning::SmallContainer);
    let subjects: Vec<&IssueRef> = small.iter().map(|f| &f.finding.subject).collect();
    assert_eq!(subjects, [&reference("o/r#8")]);
}
