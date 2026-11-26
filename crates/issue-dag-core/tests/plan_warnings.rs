//! Plan warnings (flyingrobots/taskalisk#61): Taskalisk's advisories on a
//! plan as a whole. The edge-density warning has plans below and above its
//! band that produce it, and plans inside the band, or of one open node,
//! that do not.

use std::collections::{BTreeMap, BTreeSet};

use issue_dag_core::{
    Actor, Body, Code, DENSITY_BAND, Graph, Issue, IssueRef, IssueState, Observations, Observed,
    Outcome, PLAN_WARNINGS, Parameters, PlanDetail, PlanWarning, ReadScope, RecordedForge, Repo,
    Severity, TRUST_POLICY, TrustParameters, edge_density, plan, plan_warnings,
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

/// `count` open tasks numbered from 1, each blocked by the tasks `edges`
/// name for it.
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

const fn density(warning: &PlanWarning) -> (usize, usize, f64, (f64, f64)) {
    let PlanDetail::Density {
        reduced_edges,
        open_nodes,
        density,
        band,
    } = warning.detail
    else {
        panic!("not an edge-density detail");
    };
    (reduced_edges, open_nodes, density, band)
}

#[test]
fn every_plan_warning_is_a_catalogued_warning() {
    for text in PLAN_WARNINGS {
        let code = Code::all()
            .find(|c| *c == text)
            .unwrap_or_else(|| panic!("{text} is not catalogued"));
        assert_eq!(code.severity(), Severity::Warning, "{text}");
        assert!(text.starts_with("taskalisk."), "{text}");
    }
}

/// Fifteen open tasks with no edges: density 0, below the band.
#[test]
fn a_plan_below_the_band_gives_one_warning_with_its_density() {
    let found = plan_warnings(&tasks(15, &[]));
    assert_eq!(found.len(), 1, "{found:?}");
    assert_eq!(found[0].code(), "taskalisk.edge-density");
    assert_eq!(found[0].severity(), Severity::Warning);
    assert_eq!(density(&found[0]), (0, 15, 0.0, (0.01, 0.50)));
    assert_eq!(DENSITY_BAND, (0.01, 0.50));
}

/// A chain of three: two edges over three pairs, 0.6667, above the band.
#[test]
fn a_plan_above_the_band_gives_one_warning_with_its_density() {
    let found = plan_warnings(&tasks(3, &[(1, 2), (2, 3)]));
    assert_eq!(found.len(), 1, "{found:?}");
    assert_eq!(found[0].code(), "taskalisk.edge-density");
    assert_eq!(density(&found[0]), (2, 3, 0.6667, (0.01, 0.50)));
}

/// One edge among four tasks: 1/6, 0.1667, inside the band.
#[test]
fn a_plan_inside_the_band_gives_no_warning() {
    assert_eq!(plan_warnings(&tasks(4, &[(1, 2)])), []);
}

/// Every pair of four tasks is an edge, but three of the six are redundant:
/// the reduced density is 3/6, the band's upper end, which is inside.
#[test]
fn density_counts_reduced_edges_and_the_band_includes_its_ends() {
    let all = [(1, 2), (2, 3), (3, 4), (1, 3), (1, 4), (2, 4)];
    assert_eq!(plan_warnings(&tasks(4, &all)), []);
}

/// One open node has no pairs: no density, and no warning.
#[test]
fn a_plan_of_one_open_task_gives_no_warning() {
    assert_eq!(plan_warnings(&tasks(1, &[])), []);
}

/// A chain of 64 tasks: 63 edges over 2,016 pairs, exactly 0.03125. Python's
/// `round(x, 4)` and the renderer's `{:.4}` round the exact decimal value,
/// ties to even, to 0.0312; rounding ties away from zero would give 0.0313.
#[test]
fn density_rounds_a_tie_to_even_as_python_does() {
    let chain: Vec<(u32, u32)> = (1..64).map(|n| (n, n + 1)).collect();
    assert_eq!(edge_density(&tasks(64, &chain)), Some(0.0312));
}

/// 25 tasks and 3 edges: 3/300, exactly the band's lower end, which is
/// inside it.
#[test]
fn the_band_includes_its_lower_end() {
    let graph = tasks(25, &[(1, 2), (3, 4), (5, 6)]);
    assert_eq!(edge_density(&graph), Some(0.01));
    assert_eq!(plan_warnings(&graph), []);
}

/// Two open tasks with no edge: density 0 over one pair, below the band. A
/// plan of exactly two open nodes is judged.
#[test]
fn a_plan_of_two_open_tasks_is_judged() {
    let found = plan_warnings(&tasks(2, &[]));
    assert_eq!(found.len(), 1, "{found:?}");
    assert_eq!(density(&found[0]), (0, 2, 0.0, (0.01, 0.50)));
}

/// Open o/r#3 is blocked by open o/r#2, which is blocked by closed o/r#1.
/// Only the two open nodes count: one edge over one pair, 1.0, above the
/// band. Counted as open, o/r#1 would make it 1/3, inside.
#[test]
fn a_closed_prerequisite_is_not_an_open_node() {
    let graph = graph_closing(
        &[
            (1, task(1, &[], "")),
            (2, task(2, &[1], "")),
            (3, task(3, &[2], "")),
        ],
        &[1],
    );
    let found = plan_warnings(&graph);
    assert_eq!(found.len(), 1, "{found:?}");
    assert_eq!(density(&found[0]), (1, 2, 1.0, (0.01, 0.50)));
}

/// One open node has no density.
#[test]
fn one_open_node_has_no_density() {
    assert_eq!(edge_density(&tasks(1, &[])), None);
}
