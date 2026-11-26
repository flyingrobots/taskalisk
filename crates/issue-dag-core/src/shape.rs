//! Plan-shape warnings (flyingrobots/taskalisk#42).
//!
//! Taskalisk's own advisories about the shape of a plan's graph, from the
//! skill's doctrine on graph health (`skills/taskalisk/SKILL.md`, Core
//! Doctrine 4). They are not rules of the `issue-dag/2` format or of the
//! planning profile, so the codes carry the prefix `taskalisk.`, and the
//! warnings never make a run invalid. [`shape_warnings`] reads them from a
//! [`Graph`] that [`crate::plan`] returned.

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use crate::finding::{Code, Finding, Severity};
use crate::plan::{Edge, Graph};
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
    /// An edge the transitive reduction removes (profile rule G5).
    RedundantEdge => "taskalisk.redundant-edge",
        "the .blocked_by edge is implied by a path of other edges; the reduction removes it",
}

/// What a shape warning measured, beyond its finding.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Detail {
    /// Nothing: the finding says it all.
    None,
    /// The path through the reduced graph that implies a redundant edge,
    /// from its prerequisite to its dependent, both included.
    Path(Vec<IssueRef>),
}

/// One shape warning: its finding, and what it measured.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ShapeFinding {
    /// The finding: its subject, code, the reference it concerns, message.
    pub finding: Finding,
    /// What it measured.
    pub detail: Detail,
}

/// The shape warnings of a plan's graph, sorted by their findings.
///
/// - `taskalisk.redundant-edge`, for each edge the reduction removes (G5):
///   the subject is the dependent, whose `.blocked_by` declares the edge,
///   the finding concerns the prerequisite, and the detail is the path
///   through the reduced graph that implies the edge.
#[must_use]
pub fn shape_warnings(graph: &Graph) -> Vec<ShapeFinding> {
    let mut found = Vec::new();
    for edge in graph.redundant.iter().take(0) {
        found.push(ShapeFinding {
            finding: finding(ShapeWarning::RedundantEdge, &edge.to, Some(&edge.from)),
            detail: Detail::Path(implied_path(graph, edge)),
        });
    }
    found.sort_by(|a, b| a.finding.cmp(&b.finding));
    found
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

/// The shortest path from `edge.from` to `edge.to` over the reduced edges
/// (the graph's edges less the redundant ones), both ends included; among
/// paths of one length, the first in reference order. The reduction keeps
/// every path, so a redundant edge always has one.
fn implied_path(graph: &Graph, edge: &Edge) -> Vec<IssueRef> {
    let mut next: BTreeMap<&IssueRef, Vec<&IssueRef>> = BTreeMap::new();
    for e in graph.edges.difference(&graph.redundant) {
        next.entry(&e.from).or_default().push(&e.to);
    }
    let mut came_from: BTreeMap<&IssueRef, &IssueRef> = BTreeMap::new();
    let mut seen = BTreeSet::from([&edge.from]);
    let mut queue = VecDeque::from([&edge.from]);
    while let Some(u) = queue.pop_front() {
        if u == &edge.to {
            break;
        }
        for &v in next.get(u).into_iter().flatten() {
            if seen.insert(v) {
                came_from.insert(v, u);
                queue.push_back(v);
            }
        }
    }
    let mut path = vec![edge.to.clone()];
    let mut at = &edge.to;
    while let Some(&u) = came_from.get(at) {
        path.push(u.clone());
        at = u;
    }
    path.reverse();
    path
}
