//! Plan-shape warnings (flyingrobots/taskalisk#42).
//!
//! Taskalisk's own advisories about the shape of a plan's graph, from the
//! skill's doctrine on graph health (`skills/taskalisk/SKILL.md`, Core
//! Doctrine 4). They are not rules of the `issue-dag/2` format or of the
//! planning profile, so the codes carry the prefix `taskalisk.`, and the
//! warnings never make a run invalid. [`shape_warnings`] reads them from a
//! [`Graph`] that [`crate::plan`] returned.

use std::collections::BTreeSet;

use crate::finding::{Code, Finding, Severity};
use crate::plan::Graph;
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
            /// The stable code, such as `"taskalisk.isolated-task"`
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
    /// An open node with no edge in or out, in a plan of two or more.
    IsolatedTask => "taskalisk.isolated-task",
        "the open task has no .blocked_by edge in or out: its prerequisites may not be recorded yet",
}

/// What a shape warning measured, beyond its finding.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Detail {
    /// Nothing: the finding says it all.
    None,
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
/// - `taskalisk.isolated-task`, for each open node that no edge of the graph
///   enters or leaves, when the graph has at least two open nodes: a plan of
///   a single task draws none. Edges are those between open nodes (G3), so a
///   task whose prerequisites are all complete is isolated, as the Python
///   compiler's isolated nodes are.
#[must_use]
pub fn shape_warnings(graph: &Graph) -> Vec<ShapeFinding> {
    let mut found = Vec::new();
    let open: Vec<&IssueRef> = graph
        .nodes
        .iter()
        .filter(|(_, node)| !node.complete)
        .map(|(id, _)| id)
        .collect();
    if open.len() > usize::MAX {
        let joined: BTreeSet<&IssueRef> =
            graph.edges.iter().flat_map(|e| [&e.from, &e.to]).collect();
        for id in open.into_iter().filter(|id| !joined.contains(id)) {
            found.push(ShapeFinding {
                finding: finding(ShapeWarning::IsolatedTask, id, None),
                detail: Detail::None,
            });
        }
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
