//! The renderer on a dense graph: every earlier node blocks every later
//! one, so all but the chain's edges are redundant (G5) and each needs the
//! node it is implied through. `perf_` bounds the time in a release build
//! (`cargo test --release -- --ignored perf_`); the default suite checks
//! the result on a smaller graph.

use std::collections::{BTreeMap, BTreeSet};
use std::time::{Duration, Instant};

use issue_dag_core::{
    Edge, Graph, IssueRef, Node, NodeStatus, Outcome, Parameters, ReadScope, Repo, TRUST_POLICY,
    TrustParameters,
};
use serde_json::Value;
use taskalisk::render::lines;

/// The bound a 400-node dense graph renders within, in a release build.
const DENSE_BOUND: Duration = Duration::from_secs(2);

fn r(n: u32) -> IssueRef {
    IssueRef::parse(&format!("o/r#{n}")).expect("a reference")
}

fn parameters() -> Parameters {
    Parameters {
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
    }
}

/// Open nodes `1..=n`, with an edge from each to every later one; all but
/// `(i, i + 1)` are redundant.
fn dense(n: u32) -> Outcome {
    let mut edges = BTreeSet::new();
    let mut redundant = BTreeSet::new();
    for from in 1..=n {
        for to in from + 1..=n {
            let edge = Edge {
                from: r(from),
                to: r(to),
            };
            if to > from + 1 {
                redundant.insert(edge.clone());
            }
            edges.insert(edge);
        }
    }
    let node = Node {
        status: Some(NodeStatus::Open),
        ..Node::default()
    };
    Outcome::Planned {
        findings: BTreeSet::new(),
        graph: Graph {
            nodes: (1..=n).map(|i| (r(i), node.clone())).collect(),
            edges,
            redundant,
            ready: BTreeSet::from([r(1)]),
            ..Graph::default()
        },
    }
}

fn redundant_findings(rendered: &[Value]) -> Vec<&Value> {
    rendered
        .iter()
        .filter(|l| l["code"] == "edge.redundant")
        .collect()
}

#[test]
fn a_dense_graph_renders_every_redundant_edge_with_the_node_it_is_implied_through() {
    let n = 30;
    let rendered = lines(&parameters(), &dense(n), None).expect("a plan");
    let redundant = redundant_findings(&rendered);
    let all = n * (n - 1) / 2;
    assert_eq!(redundant.len(), (all - (n - 1)) as usize);
    let number = |v: &Value| -> u32 {
        v.as_str()
            .and_then(|s| s.rsplit_once('#'))
            .and_then(|(_, n)| n.parse().ok())
            .expect("a reference")
    };
    for f in &redundant {
        let d = &f["detail"];
        let (from, to, via) = (
            number(&d["from"]),
            number(&d["to"]),
            number(&d["implied_via"]),
        );
        // Implied through a node between them: the first, as text, of the
        // source's children that reaches the target.
        assert!(from < via && via < to, "{d}");
        let first = (from + 1..to)
            .map(|w| format!("o/r#{w}"))
            .min()
            .expect("a node between");
        assert_eq!(d["implied_via"], first, "{d}");
    }
    let metrics = &rendered[0]["metrics"];
    assert_eq!(metrics["reduced_open_edge_count"], n - 1);
    assert_eq!(metrics["critical_path_length"], n);
}

#[test]
#[ignore = "a timing bound: run in a release build with --ignored perf_"]
fn perf_a_dense_graph_of_400_nodes_renders_within_the_bound() {
    let n = 400;
    let outcome = dense(n);
    let start = Instant::now();
    let rendered = lines(&parameters(), &outcome, None).expect("a plan");
    let took = start.elapsed();
    assert_eq!(
        redundant_findings(&rendered).len(),
        (n * (n - 1) / 2 - (n - 1)) as usize
    );
    assert!(took < DENSE_BOUND, "a dense graph took {took:?}");
}
