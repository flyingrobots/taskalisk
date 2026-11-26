//! Plan-shape warnings (flyingrobots/taskalisk#42).
//!
//! Taskalisk's own advisories about the shape of a plan's graph, from the
//! skill's doctrine on graph health (`skills/taskalisk/SKILL.md`, Core
//! Doctrine 4). They are not rules of the `issue-dag/2` format or of the
//! planning profile, so the codes carry the prefix `taskalisk.`, and the
//! warnings never make a run invalid. [`shape_warnings`] reads them from a
//! [`Graph`] that [`crate::plan`] returned.

use std::collections::{BTreeMap, BTreeSet};

use crate::finding::{Code, Finding, Severity};
use crate::plan::{Edge, Graph, Indexed};
use crate::reference::IssueRef;

/// Declares [`ShapeWarning`], its code and message, its list
/// [`SHAPE_WARNINGS`] and the count from one list, so a variant cannot exist
/// without its code. The list is written in the order of the codes' text,
/// which is the derived [`Ord`].
macro_rules! shape_warnings {
    ($($(#[doc = $doc:literal])* $name:ident => $code:literal, $message:literal,)+) => {
        /// A sign that a plan's graph departs from the shape the skill
        /// advises. Each is a warning; none affects validity.
        #[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub enum ShapeWarning {
            $($(#[doc = $doc])* $name,)+
        }

        impl ShapeWarning {
            /// The stable code, such as `"taskalisk.redundant-edge"`
            /// (tabled on [`crate::code`]).
            #[must_use]
            pub const fn code(self) -> &'static str {
                match self {
                    $(Self::$name => $code,)+
                }
            }

            /// Fixed text naming the sign, never issue text.
            const fn message(self) -> &'static str {
                match self {
                    $(Self::$name => $message,)+
                }
            }
        }

        /// The number of shape warnings.
        const COUNT: usize = [$($code),+].len();

        /// Every shape warning, once each, in the order of its code's text.
        pub const SHAPE_WARNINGS: [ShapeWarning; COUNT] = [$(ShapeWarning::$name),+];

        /// The codes of [`SHAPE_WARNINGS`] with their severity, in its order:
        /// this family's entry in [`crate::CODES`].
        pub const SHAPE_CODES: [(&str, Severity); COUNT] =
            [$(($code, Severity::Warning)),+];
    };
}

shape_warnings! {
    /// An open task without `.size_hours`.
    EstimateMissing => "taskalisk.estimate-missing",
        "the open task has no .size_hours: the plan cannot be reported at its true size",
    /// An open node with no edge in or out, in a plan of two or more.
    IsolatedTask => "taskalisk.isolated-task",
        "the open task has no .blocked_by edge in or out: its prerequisites may not be recorded yet",
    /// An edge the transitive reduction removes (profile rule G5).
    RedundantEdge => "taskalisk.redundant-edge",
        "the .blocked_by edge is implied by a path of other edges; the reduction removes it",
    /// A container that groups fewer than two issues.
    SmallContainer => "taskalisk.small-container",
        "the container's .children names fewer than two issues: it groups nothing",
}

/// What a shape warning measured, beyond its finding.
#[derive(Clone, Debug, PartialEq, Eq)]
#[non_exhaustive]
pub enum Detail {
    /// The node a redundant edge is implied via: the first child of its
    /// prerequisite, in the text order of references, other than its
    /// dependent, from which the dependent is reachable. The Python
    /// compiler's `implied_via`.
    ImpliedVia(IssueRef),
}

/// One shape warning: its finding, and what it measured.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ShapeFinding {
    /// The finding: its subject, code, the reference it concerns, message.
    pub finding: Finding,
    /// What it measured, or `None` when the finding says it all.
    pub detail: Option<Detail>,
}

/// The shape warnings of a plan's graph, sorted by their findings.
///
/// - `taskalisk.estimate-missing`, for each open task without `.size_hours`
///   ([`crate::Node::size_hours`]): an opaque node has no document to hold
///   the key, and a closed node or a container draws none. It has no detail.
/// - `taskalisk.isolated-task`, for each open node that no edge of the graph
///   enters or leaves, when the graph has at least two open nodes: a plan of
///   a single task draws none. Edges are those between open nodes (G3), so a
///   task whose prerequisites are all complete is isolated, as the Python
///   compiler's isolated nodes are. It has no detail.
/// - `taskalisk.redundant-edge`, for each edge the reduction removes (G5):
///   the subject is the dependent, whose `.blocked_by` declares the edge,
///   the finding concerns the prerequisite, and the detail is the node the
///   edge is implied via ([`Detail::ImpliedVia`]).
/// - `taskalisk.small-container`, for each open container of the graph whose
///   `.children` names fewer than two distinct issues (a reference to the
///   container itself is not a child). It has no detail.
#[must_use]
pub fn shape_warnings(graph: &Graph) -> Vec<ShapeFinding> {
    let mut found = Vec::new();
    let mut via = Via::of(graph);
    for edge in &graph.redundant {
        found.push(ShapeFinding {
            finding: finding(ShapeWarning::RedundantEdge, &edge.to, Some(&edge.from)),
            detail: Some(Detail::ImpliedVia(via.of_edge(edge))),
        });
    }
    estimates_missing(graph, &mut found);
    isolated(graph, &mut found);
    small_containers(graph, &mut found);
    found.sort_by(|a, b| a.finding.cmp(&b.finding));
    found
}

/// `taskalisk.estimate-missing`: each open task with a document and no
/// `.size_hours`.
fn estimates_missing(graph: &Graph, found: &mut Vec<ShapeFinding>) {
    for (id, node) in &graph.nodes {
        if !node.complete && !node.opaque && node.size_hours.is_none() {
            found.push(ShapeFinding {
                finding: finding(ShapeWarning::EstimateMissing, id, None),
                detail: None,
            });
        }
    }
}

/// `taskalisk.isolated-task`: each open node no edge joins, in a graph of
/// two or more open nodes.
fn isolated(graph: &Graph, found: &mut Vec<ShapeFinding>) {
    let open: Vec<&IssueRef> = graph
        .nodes
        .iter()
        .filter(|(_, node)| !node.complete)
        .map(|(id, _)| id)
        .collect();
    if open.len() < 2 {
        return;
    }
    let joined: BTreeSet<&IssueRef> = graph.edges.iter().flat_map(|e| [&e.from, &e.to]).collect();
    for id in open.into_iter().filter(|id| !joined.contains(id)) {
        found.push(ShapeFinding {
            finding: finding(ShapeWarning::IsolatedTask, id, None),
            detail: None,
        });
    }
}

/// `taskalisk.small-container`: each open container of fewer than two
/// distinct children.
fn small_containers(graph: &Graph, found: &mut Vec<ShapeFinding>) {
    for (id, children) in &graph.containers {
        if !graph.closed_containers.contains(id)
            && children.iter().collect::<BTreeSet<_>>().len() < 2
        {
            found.push(ShapeFinding {
                finding: finding(ShapeWarning::SmallContainer, id, None),
                detail: None,
            });
        }
    }
}

/// The finding of `warning` for `subject`, about `concerns`.
fn finding(warning: ShapeWarning, subject: &IssueRef, concerns: Option<&IssueRef>) -> Finding {
    Finding::coded(
        subject.clone(),
        Code::of(warning.code()),
        concerns.cloned(),
        warning.message(),
    )
}

/// What each open node reaches, built once for a graph, and the children of
/// each prerequisite in the text order of their references, built when
/// first asked for: enough to name the node each redundant edge is implied
/// via without a search per edge.
struct Via {
    indexed: Indexed,
    position: BTreeMap<IssueRef, usize>,
    /// For each open node, by position, a bit set of the nodes it reaches.
    descendants: Vec<Vec<u64>>,
    /// The children of a node, by position, in reference text order.
    sorted: BTreeMap<usize, Vec<usize>>,
}

impl Via {
    /// The descendant sets of `graph`'s open nodes, over all its edges, in
    /// reverse topological order. Empty when nothing is redundant, which
    /// includes a graph with a cycle (G5 reduces only an acyclic one).
    fn of(graph: &Graph) -> Self {
        let indexed = Indexed::of(graph);
        let mut descendants = Vec::new();
        if !graph.redundant.is_empty() {
            let (order, _) = indexed.kahn();
            let words = indexed.ids.len().div_ceil(64);
            descendants = vec![vec![0_u64; words]; indexed.ids.len()];
            for &u in order.iter().rev() {
                let mut set = vec![0_u64; words];
                for &c in &indexed.children[u] {
                    set[c / 64] |= 1 << (c % 64);
                    for (word, child_word) in set.iter_mut().zip(&descendants[c]) {
                        *word |= child_word;
                    }
                }
                descendants[u] = set;
            }
        }
        let position = indexed
            .ids
            .iter()
            .enumerate()
            .map(|(i, id)| (id.clone(), i))
            .collect();
        Self {
            indexed,
            position,
            descendants,
            sorted: BTreeMap::new(),
        }
    }

    /// The node the redundant `edge` is implied via: the first child of its
    /// prerequisite, in the text order of references, other than its
    /// dependent, that reaches its dependent. The Python compiler picks its
    /// `implied_via` so. A redundant edge always has one; if it had none,
    /// the prerequisite itself is named.
    fn of_edge(&mut self, edge: &Edge) -> IssueRef {
        let (Some(&u), Some(&v)) = (self.position.get(&edge.from), self.position.get(&edge.to))
        else {
            return edge.from.clone();
        };
        let indexed = &self.indexed;
        let children = self.sorted.entry(u).or_insert_with(|| {
            let mut children = indexed.children[u].clone();
            children.sort_by_cached_key(|&c| indexed.ids[c].to_string());
            children
        });
        children
            .iter()
            .find(|&&w| w != v && self.descendants[w][v / 64] & (1 << (v % 64)) != 0)
            .map_or_else(|| edge.from.clone(), |&w| self.indexed.ids[w].clone())
    }
}
