//! Ranking under `issue-dag-planning/2` (rules K1 to K8): the score of each
//! open node, the rank order, the waves and the critical path of a graph a
//! run reported.

use std::collections::BTreeMap;

use crate::plan::{Graph, Indexed, NodeStatus};
use crate::reference::IssueRef;

/// The ranking of a graph's open nodes (rules K1 to K8).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Ranking {
    /// The score of each open node (rule K5).
    pub scores: BTreeMap<IssueRef, u64>,
    /// Every open node in rank order (rule K6).
    pub order: Vec<IssueRef>,
    /// The ready set in rank order (rules Q1 and K6).
    pub ready: Vec<IssueRef>,
    /// The waves (rule K7): wave `k` holds the nodes of level `k`, each in
    /// rank order. Wave 0 is the ready set.
    pub waves: Vec<Vec<IssueRef>>,
    /// The critical path (rule K8), from its first node to its last; empty
    /// when the graph has no open node.
    pub critical_path: Vec<IssueRef>,
}

/// Ranks the open nodes of a graph. `None` when its edges form a cycle
/// (rule G4), where no rank is defined; a graph a run reports never does.
#[must_use]
pub fn rank(graph: &Graph) -> Option<Ranking> {
    let indexed = Indexed::of(graph);
    let (topological, cyclic) = indexed.kahn();
    if !cyclic.is_empty() {
        return None;
    }
    let ids = &indexed.ids;
    let n = ids.len();
    // K6 compares identifiers as text: the canonical form, by code point,
    // which is the byte order of its UTF-8.
    let text: Vec<String> = ids.iter().map(ToString::to_string).collect();
    let position: BTreeMap<&IssueRef, usize> =
        ids.iter().enumerate().map(|(i, id)| (id, i)).collect();
    // The reduced graph (G5). It has the reachability of the graph, so K1,
    // K2 and K7 read it too.
    let mut children = vec![Vec::new(); n];
    let mut parents = vec![Vec::new(); n];
    for edge in graph.edges.difference(&graph.redundant) {
        if let (Some(&from), Some(&to)) = (position.get(&edge.from), position.get(&edge.to)) {
            children[from].push(to);
            parents[to].push(from);
        }
    }

    // K1 and K2, in reverse topological order: descendant sets as bit sets.
    let words = n.div_ceil(64);
    let mut below = vec![Vec::new(); n];
    let mut depth = vec![1_u64; n];
    for &u in topological.iter().rev() {
        let mut set = vec![0_u64; words];
        for &c in &children[u] {
            set[c / 64] |= 1 << (c % 64);
            for (word, child_word) in set.iter_mut().zip(&below[c]) {
                *word |= child_word;
            }
            depth[u] = depth[u].max(depth[c] + 1);
        }
        below[u] = set;
    }
    // K7, in topological order.
    let mut level = vec![0_usize; n];
    for &u in &topological {
        for &c in &children[u] {
            level[c] = level[c].max(level[u] + 1);
        }
    }

    // K3 to K5.
    let score: Vec<u64> = (0..n)
        .map(|u| {
            let status = graph.nodes.get(&ids[u]).and_then(|node| node.status);
            let descendants: u64 = below[u].iter().map(|w| u64::from(w.count_ones())).sum();
            1000 * u64::from(in_flight(status))
                + 500 * u64::from(status == Some(NodeStatus::Parked))
                + 100 * descendants
                + 10 * depth[u]
                + children[u].len() as u64
        })
        .collect();

    // K6.
    let mut order: Vec<usize> = (0..n).collect();
    order.sort_by(|&a, &b| score[b].cmp(&score[a]).then_with(|| text[a].cmp(&text[b])));

    // K7: each wave in rank order.
    let mut waves: Vec<Vec<IssueRef>> = vec![Vec::new(); level.iter().max().map_or(0, |l| l + 1)];
    for &u in &order {
        waves[level[u]].push(ids[u].clone());
    }

    // K8: from the open node with the greatest (level, identifier), back
    // through the reduced predecessor with the greatest pair.
    let key = |u: &usize| (level[*u], &text[*u]);
    let mut critical_path = Vec::new();
    let mut current = (0..n).max_by_key(key);
    while let Some(u) = current {
        critical_path.push(ids[u].clone());
        current = parents[u].iter().copied().max_by_key(key);
    }
    critical_path.reverse();

    Some(Ranking {
        scores: (0..n).map(|u| (ids[u].clone(), score[u])).collect(),
        ready: order
            .iter()
            .filter(|&&u| graph.ready.contains(&ids[u]))
            .map(|&u| ids[u].clone())
            .collect(),
        order: order.iter().map(|&u| ids[u].clone()).collect(),
        waves,
        critical_path,
    })
}

/// K4: whether a status is in flight.
const fn in_flight(status: Option<NodeStatus>) -> bool {
    matches!(
        status,
        Some(NodeStatus::InProgress | NodeStatus::Wip | NodeStatus::InReview)
    )
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, BTreeSet};

    use super::{Ranking, rank};
    use crate::plan::{Edge, Graph, Node, NodeStatus};
    use crate::reference::IssueRef;

    fn r(n: u32) -> IssueRef {
        IssueRef::parse(&format!("o/r#{n}")).expect("a reference")
    }

    fn open(status: NodeStatus) -> Node {
        Node {
            complete: false,
            opaque: false,
            untrusted: false,
            status: Some(status),
            holds: BTreeSet::new(),
            meters: Vec::new(),
        }
    }

    /// A graph of open nodes `1..=n` with these edges, the redundant ones
    /// named, and the ready set rule Q1 gives.
    fn graph(n: u32, edges: &[(u32, u32)], redundant: &[(u32, u32)]) -> Graph {
        let edge = |&(from, to): &(u32, u32)| Edge {
            from: r(from),
            to: r(to),
        };
        let edges: BTreeSet<Edge> = edges.iter().map(edge).collect();
        let targets: BTreeSet<IssueRef> = edges.iter().map(|e| e.to.clone()).collect();
        Graph {
            nodes: (1..=n).map(|i| (r(i), open(NodeStatus::Open))).collect(),
            ready: (1..=n).map(r).filter(|i| !targets.contains(i)).collect(),
            redundant: redundant.iter().map(edge).collect(),
            edges,
            ..Graph::default()
        }
    }

    fn ids(items: &[u32]) -> Vec<IssueRef> {
        items.iter().copied().map(r).collect()
    }

    fn ranked(graph: &Graph) -> Ranking {
        rank(graph).expect("an acyclic graph")
    }

    #[test]
    fn k5_the_score_counts_descendants_depth_and_reduced_out_degree() {
        // 1 -> 2 -> 3, and 1 -> 3, which the reduction removes.
        let g = graph(3, &[(1, 2), (2, 3), (1, 3)], &[(1, 3)]);
        let ranking = ranked(&g);
        // 1: two descendants, depth 3, one reduced out-edge.
        assert_eq!(ranking.scores[&r(1)], 200 + 30 + 1);
        assert_eq!(ranking.scores[&r(2)], 100 + 20 + 1);
        assert_eq!(ranking.scores[&r(3)], 10);
    }

    #[test]
    fn k4_in_flight_and_parked_statuses_add_their_weights() {
        let mut g = graph(6, &[], &[]);
        let statuses = [
            (1, NodeStatus::InProgress, 1010),
            (2, NodeStatus::Wip, 1010),
            (3, NodeStatus::InReview, 1010),
            (4, NodeStatus::Parked, 510),
            (5, NodeStatus::Blocked, 10),
            (6, NodeStatus::Open, 10),
        ];
        for (n, status, _) in statuses {
            g.nodes.insert(r(n), open(status));
        }
        let ranking = ranked(&g);
        for (n, _, score) in statuses {
            assert_eq!(ranking.scores[&r(n)], score, "o/r#{n}");
        }
    }

    #[test]
    fn k6_equal_scores_are_ordered_by_identifier_as_text() {
        let g = graph(10, &[], &[]);
        let ranking = ranked(&g);
        assert_eq!(ranking.ready, ids(&[1, 10, 2, 3, 4, 5, 6, 7, 8, 9]));
        assert_eq!(ranking.order, ranking.ready);
    }

    #[test]
    fn k6_higher_scores_rank_first() {
        // 3 -> 1: o/r#3 (score 121) outranks o/r#1 and o/r#2 (10 each).
        let g = graph(3, &[(3, 1)], &[]);
        let ranking = ranked(&g);
        assert_eq!(ranking.order, ids(&[3, 1, 2]));
        assert_eq!(ranking.ready, ids(&[3, 2]));
    }

    #[test]
    fn k7_waves_hold_the_nodes_of_each_level_in_rank_order() {
        // 1 -> 2 -> 4, 3 -> 4, 5 alone.
        let g = graph(5, &[(1, 2), (2, 4), (3, 4)], &[]);
        let ranking = ranked(&g);
        assert_eq!(ranking.waves, vec![ids(&[1, 3, 5]), ids(&[2]), ids(&[4])]);
        assert_eq!(ranking.waves[0], ranking.ready);
    }

    #[test]
    fn k8_the_critical_path_follows_the_greatest_level_and_identifier() {
        // 1 -> 2 -> 6, 5 -> 6 and 3 -> 4: the path ends at o/r#6, the one
        // node of level 2, and steps back to the predecessor of greater
        // level, o/r#2, not o/r#5.
        let g = graph(6, &[(1, 2), (2, 6), (5, 6), (3, 4)], &[]);
        let ranking = ranked(&g);
        assert_eq!(ranking.critical_path, ids(&[1, 2, 6]));
    }

    #[test]
    fn k8_the_critical_path_uses_the_reduced_graph() {
        // 1 -> 2 -> 3 and 1 -> 3: 3's reduced predecessor is 2 only.
        let g = graph(3, &[(1, 2), (2, 3), (1, 3)], &[(1, 3)]);
        assert_eq!(ranked(&g).critical_path, ids(&[1, 2, 3]));
    }

    #[test]
    fn k8_ties_on_level_take_the_greater_identifier_as_text() {
        let g = graph(10, &[], &[]);
        assert_eq!(ranked(&g).critical_path, ids(&[9]));
    }

    #[test]
    fn k8_no_open_node_gives_no_critical_path() {
        let mut g = graph(1, &[], &[]);
        g.nodes.get_mut(&r(1)).expect("node").complete = true;
        g.ready.clear();
        let ranking = ranked(&g);
        assert_eq!(ranking.critical_path, Vec::<IssueRef>::new());
        assert_eq!(ranking.waves, Vec::<Vec<IssueRef>>::new());
        assert_eq!(ranking.scores, BTreeMap::new());
    }

    #[test]
    fn g4_a_cycle_has_no_ranking() {
        let g = graph(2, &[(1, 2), (2, 1)], &[]);
        assert_eq!(rank(&g), None);
    }

    #[test]
    fn complete_nodes_are_not_ranked() {
        let mut g = graph(2, &[], &[]);
        g.nodes.get_mut(&r(2)).expect("node").complete = true;
        g.ready.remove(&r(2));
        let ranking = ranked(&g);
        assert_eq!(ranking.scores, BTreeMap::from([(r(1), 10)]));
    }
}
