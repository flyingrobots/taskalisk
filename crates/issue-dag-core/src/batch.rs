//! Resources and batch selection under `issue-dag-planning/2` (rules B1 to
//! B5): which dispatchable ready nodes can start together.

use std::collections::{BTreeMap, BTreeSet};
use std::ops::Bound;

use crate::plan::Graph;
use crate::rank::Ranking;
use crate::record::MeterClaim;
use crate::reference::IssueRef;

/// Why rule B5 skipped a node.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Skip {
    /// One of its keys conflicts with a key of a node already in the batch.
    HoldsConflict,
    /// These semaphores would exceed their capacity.
    SemaphoreFull(BTreeSet<String>),
}

impl Skip {
    /// The reason as the profile writes it.
    #[must_use]
    pub const fn reason(&self) -> &'static str {
        match self {
            Self::HoldsConflict => "holds conflict",
            Self::SemaphoreFull(_) => "semaphore full",
        }
    }
}

/// The batch of a run (rule B5).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Batch {
    /// The nodes that joined, in order of selection.
    pub selected: Vec<IssueRef>,
    /// The nodes skipped, in the order considered, with why.
    pub skipped: Vec<(IssueRef, Skip)>,
    /// The semaphores without a capacity named by a claim of a node B5
    /// considered (rule B3).
    pub unknown_capacity: BTreeSet<String>,
}

/// B1: whether two resource keys conflict.
#[must_use]
pub fn keys_conflict(a: &str, b: &str) -> bool {
    let (a, b) = (subtree(a), subtree(b));
    a == b || a.starts_with(b.as_str()) || b.starts_with(a.as_str())
}

/// B1: `T(k)`, the key as a subtree: `k` when it ends with `/`, else `k/`.
fn subtree(key: &str) -> String {
    if key.ends_with('/') {
        key.to_owned()
    } else {
        format!("{key}/")
    }
}

/// B5: selects the batch from the dispatchable ready nodes in rank order,
/// with the capacities of the run's parameters.
#[must_use]
pub fn select(graph: &Graph, ranking: &Ranking, capacities: &BTreeMap<String, u64>) -> Batch {
    let dispatchable = graph.dispatchable();
    let mut selection = Selection::new(capacities);
    let mut batch = Batch::default();
    for id in ranking.ready.iter().filter(|id| dispatchable.contains(*id)) {
        let Some(node) = graph.nodes.get(id) else {
            continue;
        };
        let claim = Claim::of(&node.holds, &node.meters);
        // B3: every semaphore of a considered node that has no capacity.
        batch.unknown_capacity.extend(
            claim
                .need
                .keys()
                .filter(|name| !capacities.contains_key(*name))
                .cloned(),
        );
        // The decision and the reason for a skip are one value.
        match selection.decide(&claim) {
            Ok(()) => {
                selection.join(claim);
                batch.selected.push(id.clone());
            }
            Err(skip) => batch.skipped.push((id.clone(), skip)),
        }
    }
    batch
}

/// What a node claims: its keys as subtrees (B1) and its need for each
/// semaphore (B4).
struct Claim {
    subtrees: BTreeSet<String>,
    need: BTreeMap<String, u64>,
}

impl Claim {
    fn of(holds: &BTreeSet<String>, meters: &[MeterClaim]) -> Self {
        let mut need = BTreeMap::new();
        for meter in meters {
            *need.entry(meter.name.clone()).or_insert(0) += u64::from(meter.slots);
        }
        Self {
            subtrees: holds.iter().map(|k| subtree(k)).collect(),
            need,
        }
    }
}

/// The batch so far: the subtrees its nodes hold and the slots they use.
struct Selection<'a> {
    capacities: &'a BTreeMap<String, u64>,
    held: BTreeSet<String>,
    used: BTreeMap<String, u64>,
}

impl<'a> Selection<'a> {
    const fn new(capacities: &'a BTreeMap<String, u64>) -> Self {
        Self {
            capacities,
            held: BTreeSet::new(),
            used: BTreeMap::new(),
        }
    }

    /// B5 steps 1 and 2 for a node: it may join, or why it is skipped.
    fn decide(&self, claim: &Claim) -> Result<(), Skip> {
        if claim.subtrees.iter().any(|t| self.conflicts(t)) {
            return Err(Skip::HoldsConflict);
        }
        let full: BTreeSet<String> = claim
            .need
            .iter()
            .filter(|(name, need)| {
                let used = self.used.get(*name).copied().unwrap_or(0);
                // B3: a semaphore without a capacity has capacity 1.
                let capacity = self.capacities.get(*name).copied().unwrap_or(1);
                used.saturating_add(**need) > capacity
            })
            .map(|(name, _)| name.clone())
            .collect();
        if full.is_empty() {
            Ok(())
        } else {
            Err(Skip::SemaphoreFull(full))
        }
    }

    /// B5 step 3.
    fn join(&mut self, claim: Claim) {
        self.held.extend(claim.subtrees);
        for (name, need) in claim.need {
            *self.used.entry(name).or_insert(0) += need;
        }
    }

    /// B1 for a subtree `t` against every held subtree, without a scan:
    /// a held subtree that is a prefix of `t` ends at one of `t`'s `/`, and
    /// the held subtrees that `t` is a prefix of sort right after `t`.
    fn conflicts(&self, t: &str) -> bool {
        let held_prefix = t
            .match_indices('/')
            .any(|(i, _)| self.held.contains(&t[..=i]));
        held_prefix
            || self
                .held
                .range::<str, _>((Bound::Included(t), Bound::Unbounded))
                .next()
                .is_some_and(|h| h.starts_with(t))
    }
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, BTreeSet};

    use super::{Batch, Claim, Selection, Skip, keys_conflict, select, subtree};
    use crate::plan::{Graph, Node, NodeStatus};
    use crate::rank::rank;
    use crate::record::MeterClaim;
    use crate::reference::IssueRef;

    fn r(n: u32) -> IssueRef {
        IssueRef::parse(&format!("o/r#{n}")).expect("a reference")
    }

    /// An open, ready node with these keys and claims (`name*slots`).
    fn node(holds: &[&str], meters: &[&str]) -> Node {
        Node {
            complete: false,
            opaque: false,
            untrusted: false,
            status: Some(NodeStatus::Open),
            holds: holds.iter().map(|k| (*k).to_owned()).collect(),
            meters: meters
                .iter()
                .map(|m| MeterClaim::parse(m).expect("a claim"))
                .collect(),
            ..Node::default()
        }
    }

    /// A graph with no edges: every node ready, ranked by identifier as
    /// text (o/r#1 first, then o/r#2, ...).
    fn ready(nodes: Vec<Node>) -> Graph {
        let nodes: BTreeMap<IssueRef, Node> = nodes
            .into_iter()
            .zip(1..)
            .map(|(node, n)| (r(n), node))
            .collect();
        Graph {
            ready: nodes.keys().cloned().collect(),
            nodes,
            ..Graph::default()
        }
    }

    fn batch(graph: &Graph, capacities: &[(&str, u64)]) -> Batch {
        let ranking = rank(graph).expect("an acyclic graph");
        let capacities = capacities
            .iter()
            .map(|(name, n)| ((*name).to_owned(), *n))
            .collect();
        select(graph, &ranking, &capacities)
    }

    fn full(names: &[&str]) -> Skip {
        Skip::SemaphoreFull(names.iter().map(|n| (*n).to_owned()).collect())
    }

    #[test]
    fn b1_keys_are_subtrees() {
        assert!(keys_conflict("docs", "docs"));
        assert!(keys_conflict("docs", "docs/plans"));
        assert!(keys_conflict("docs/plans", "docs"));
        assert!(keys_conflict("docs/", "docs/plans"));
        assert!(keys_conflict("docs/", "docs"));
        assert!(!keys_conflict("doc", "docs"));
        assert!(!keys_conflict("docs/a", "docs/b"));
        assert!(!keys_conflict("docs/plans", "docs/plans-old"));
    }

    #[test]
    fn b1_the_held_index_agrees_with_the_rule_for_every_pair() {
        let keys = [
            "a", "a/", "a/b", "a/b/", "a/bc", "ab", "a//", "a/b/c", "b", "", "/", "a-b", "a.b",
        ];
        let capacities = BTreeMap::new();
        for held in keys {
            let mut selection = Selection::new(&capacities);
            selection.join(Claim::of(&BTreeSet::from([held.to_owned()]), &[]));
            for key in keys {
                assert_eq!(
                    selection.conflicts(&subtree(key)),
                    keys_conflict(held, key),
                    "held {held:?}, key {key:?}"
                );
            }
        }
    }

    #[test]
    fn b5_a_holds_conflict_skips_the_lower_ranked_node() {
        let g = ready(vec![node(&["docs"], &[]), node(&["docs/plans"], &[])]);
        let b = batch(&g, &[]);
        assert_eq!(b.selected, vec![r(1)]);
        assert_eq!(b.skipped, vec![(r(2), Skip::HoldsConflict)]);
    }

    #[test]
    fn b2_keys_conflict_across_repositories() {
        let mut g = ready(vec![node(&["db"], &[])]);
        let other = IssueRef::parse("p/q#1").expect("a reference");
        g.nodes.insert(other.clone(), node(&["db"], &[]));
        g.ready.insert(other.clone());
        let b = batch(&g, &[]);
        assert_eq!(b.selected, vec![r(1)]);
        assert_eq!(b.skipped, vec![(other, Skip::HoldsConflict)]);
    }

    #[test]
    fn b5_a_holds_conflict_is_the_reason_even_when_a_semaphore_is_full() {
        let g = ready(vec![node(&["k"], &["gpu"]), node(&["k"], &["gpu"])]);
        let b = batch(&g, &[("gpu", 1)]);
        assert_eq!(b.skipped, vec![(r(2), Skip::HoldsConflict)]);
    }

    #[test]
    fn b4_the_need_is_the_sum_of_the_claims() {
        let g = ready(vec![node(&[], &["gpu*2"]), node(&[], &["gpu", "gpu"])]);
        let b = batch(&g, &[("gpu", 3)]);
        assert_eq!(b.selected, vec![r(1)]);
        assert_eq!(b.skipped, vec![(r(2), full(&["gpu"]))]);
        let b = batch(&g, &[("gpu", 4)]);
        assert_eq!(b.selected, vec![r(1), r(2)]);
    }

    #[test]
    fn b5_semaphore_full_names_every_semaphore_over_capacity() {
        let g = ready(vec![
            node(&[], &["a", "b", "c"]),
            node(&[], &["a", "b", "c"]),
        ]);
        let b = batch(&g, &[("a", 1), ("b", 1), ("c", 2)]);
        assert_eq!(b.skipped, vec![(r(2), full(&["a", "b"]))]);
    }

    #[test]
    fn b5_a_node_whose_own_need_exceeds_the_capacity_is_skipped() {
        let g = ready(vec![node(&[], &["gpu*3"])]);
        let b = batch(&g, &[("gpu", 2)]);
        assert_eq!(b.selected, Vec::<IssueRef>::new());
        assert_eq!(b.skipped, vec![(r(1), full(&["gpu"]))]);
    }

    #[test]
    fn b3_an_unknown_capacity_is_one_and_is_reported() {
        let g = ready(vec![node(&[], &["gpu"]), node(&[], &["gpu"])]);
        let b = batch(&g, &[]);
        assert_eq!(b.selected, vec![r(1)]);
        assert_eq!(b.skipped, vec![(r(2), full(&["gpu"]))]);
        assert_eq!(b.unknown_capacity, BTreeSet::from(["gpu".to_owned()]));
        let b = batch(&g, &[("gpu", 2)]);
        assert_eq!(b.selected, vec![r(1), r(2)]);
        assert_eq!(b.unknown_capacity, BTreeSet::new());
    }

    #[test]
    fn b3_only_names_of_considered_nodes_are_reported() {
        // o/r#2 is blocked, o/r#3 waits on o/r#1, o/r#4 is opaque: none is
        // considered, so their semaphores are not reported.
        let mut blocked = node(&[], &["x"]);
        blocked.status = Some(NodeStatus::Blocked);
        let mut opaque = node(&[], &["z"]);
        opaque.opaque = true;
        let mut g = ready(vec![
            node(&["k"], &["a"]),
            blocked,
            node(&[], &["y"]),
            opaque,
            node(&["k"], &["b"]),
        ]);
        g.edges.insert(crate::plan::Edge {
            from: r(1),
            to: r(3),
        });
        g.ready.remove(&r(3));
        let b = batch(&g, &[]);
        // o/r#5 is considered, and skipped for its key: its claim counts.
        assert_eq!(b.skipped, vec![(r(5), Skip::HoldsConflict)]);
        assert_eq!(
            b.unknown_capacity,
            BTreeSet::from(["a".to_owned(), "b".to_owned()])
        );
    }

    #[test]
    fn q2_only_dispatchable_nodes_enter_the_batch_in_rank_order() {
        let mut untrusted = node(&[], &[]);
        untrusted.untrusted = true;
        untrusted.opaque = true;
        let mut active = node(&[], &[]);
        active.status = Some(NodeStatus::InProgress);
        let g = ready(vec![node(&[], &[]), untrusted, active]);
        let b = batch(&g, &[]);
        assert_eq!(b.selected, vec![r(3), r(1)]);
        assert_eq!(b.skipped, Vec::new());
    }
}

#[cfg(test)]
mod scale {
    use std::collections::BTreeSet;
    use std::time::{Duration, Instant};

    use super::select;
    use crate::plan::{Edge, Graph, Node, NodeStatus};
    use crate::rank::rank;
    use crate::record::MeterClaim;
    use crate::reference::IssueRef;

    /// The bound ranking and selection must finish within, in a debug
    /// build, as for planning (`plan::tests::LARGE_GRAPH_BOUND`).
    const BOUND: Duration = Duration::from_secs(1);
    const LARGE: u32 = 5_000;

    fn r(n: u32) -> IssueRef {
        IssueRef::parse(&format!("o/r#{n}")).expect("a reference")
    }

    fn node(n: u32) -> Node {
        Node {
            complete: false,
            opaque: false,
            untrusted: false,
            status: Some(NodeStatus::Open),
            // Distinct keys under one root, and a shared semaphore.
            holds: BTreeSet::from([format!("src/{n}"), format!("docs/{n}/")]),
            meters: vec![MeterClaim {
                name: "ci".to_owned(),
                slots: 1,
            }],
            ..Node::default()
        }
    }

    fn graph(edges: impl IntoIterator<Item = (u32, u32)>, nodes: u32) -> Graph {
        let edges: BTreeSet<Edge> = edges
            .into_iter()
            .map(|(from, to)| Edge {
                from: r(from),
                to: r(to),
            })
            .collect();
        let targets: BTreeSet<IssueRef> = edges.iter().map(|e| e.to.clone()).collect();
        Graph {
            nodes: (1..=nodes).map(|n| (r(n), node(n))).collect(),
            ready: (1..=nodes)
                .map(r)
                .filter(|id| !targets.contains(id))
                .collect(),
            edges,
            ..Graph::default()
        }
    }

    #[test]
    fn a_chain_of_5000_nodes_ranks_and_selects_within_the_bound() {
        let g = graph((1..LARGE).map(|n| (n, n + 1)), LARGE);
        let start = Instant::now();
        let ranking = rank(&g).expect("acyclic");
        let batch = select(&g, &ranking, &[("ci".to_owned(), 1)].into());
        let took = start.elapsed();
        println!("took {took:?}");
        assert_eq!(
            ranking.scores[&r(1)],
            100 * u64::from(LARGE - 1) + 10 * u64::from(LARGE) + 1
        );
        assert_eq!(ranking.waves.len(), LARGE as usize);
        assert_eq!(ranking.critical_path.len(), LARGE as usize);
        assert_eq!(batch.selected, vec![r(1)]);
        assert!(took < BOUND, "a chain took {took:?}");
    }

    #[test]
    fn a_wide_frontier_of_5000_nodes_ranks_and_selects_within_the_bound() {
        // Every node is ready, so B5 considers 5000 nodes against a batch
        // that grows to 5000 nodes holding 10000 keys.
        let g = graph([], LARGE);
        let capacities = [("ci".to_owned(), u64::from(LARGE))].into();
        let start = Instant::now();
        let ranking = rank(&g).expect("acyclic");
        let batch = select(&g, &ranking, &capacities);
        let took = start.elapsed();
        println!("took {took:?}");
        assert_eq!(batch.selected.len(), LARGE as usize);
        assert_eq!(batch.skipped, Vec::new());
        assert!(took < BOUND, "a wide frontier took {took:?}");
    }

    #[test]
    fn a_fan_of_5000_nodes_ranks_within_the_bound() {
        // o/r#1 blocks every other node and o/r#2 blocks the rest too: the
        // edges from o/r#1 to o/r#3.. are redundant (G5).
        let mut edges: Vec<(u32, u32)> = (2..=LARGE).map(|n| (1, n)).collect();
        edges.extend((3..=LARGE).map(|n| (2, n)));
        let mut g = graph(edges, LARGE);
        g.redundant = (3..=LARGE)
            .map(|n| Edge {
                from: r(1),
                to: r(n),
            })
            .collect();
        let start = Instant::now();
        let ranking = rank(&g).expect("acyclic");
        let took = start.elapsed();
        println!("took {took:?}");
        assert_eq!(
            ranking.scores[&r(1)],
            100 * u64::from(LARGE - 1) + 10 * 3 + 1
        );
        // Every node from o/r#3 has level 2; the greatest identifier as text
        // (K8) is o/r#999, not o/r#5000.
        assert_eq!(ranking.critical_path, vec![r(1), r(2), r(999)]);
        assert!(took < BOUND, "a fan took {took:?}");
    }
}
