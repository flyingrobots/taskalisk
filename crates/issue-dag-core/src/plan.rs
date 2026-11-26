//! A planning run under `issue-dag-planning/2`: discovery and closure
//! (rules D1 to D10), admission (I6), the cross-document rules (X1 to X3),
//! the graph (G1 to G5), status (S1, S2), readiness (Q1, Q2) and the outcome
//! (F1 to F5). Ranking and batch selection (K and B rules) are not here.

use core::fmt;
use std::collections::{BTreeMap, BTreeSet};

use crate::forge::Forge;
use crate::label::Label;
use crate::observation::{Missing, Parameters};
use crate::record::MeterClaim;
use crate::reference::IssueRef;

/// The label of a finding (profile rule F5).
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Rule {
    /// A document's violation or warning, labelled as format rule V12 states
    /// (X1 included).
    Document(Label),
    /// A reference outside the read scope.
    D3,
    /// A reference to a pull request.
    D4,
    /// A transferred reference.
    D5,
    /// A prerequisite that is a container.
    X2,
    /// An unknown prerequisite.
    X3,
    /// A node of a cycle, or downstream of one.
    G4,
}

impl Rule {
    /// The label as the specification writes it.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Document(label) => label.as_str(),
            Self::D3 => "D3",
            Self::D4 => "D4",
            Self::D5 => "D5",
            Self::X2 => "X2",
            Self::X3 => "X3",
            Self::G4 => "G4",
        }
    }

    /// Whether a finding with this label makes the run invalid. Only a
    /// warning (V10) does not.
    #[must_use]
    pub const fn is_violation(self) -> bool {
        !matches!(self, Self::Document(Label::V10))
    }
}

impl fmt::Display for Rule {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// A finding (profile rule F5): the issue that receives it, its label, and
/// for D3, D5, X2 and X3 the reference it concerns.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Finding {
    /// The issue that receives it.
    pub subject: IssueRef,
    /// The label of the rule.
    pub rule: Rule,
    /// The reference it concerns.
    pub concerns: Option<IssueRef>,
}

/// The status of an open node (rule S2).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum NodeStatus {
    /// `in-review`: a linked pull request is not a draft.
    InReview,
    /// `wip`: every linked pull request is a draft.
    Wip,
    /// `blocked`: opaque, or `.status: blocked`.
    Blocked,
    /// `in-progress`: `.status: active`.
    InProgress,
    /// `parked`: `.status: parked`.
    Parked,
    /// `open`.
    Open,
}

impl NodeStatus {
    /// The status as the profile writes it.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InReview => "in-review",
            Self::Wip => "wip",
            Self::Blocked => "blocked",
            Self::InProgress => "in-progress",
            Self::Parked => "parked",
            Self::Open => "open",
        }
    }
}

/// A node of the graph (rule G1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Node {
    /// Whether its issue is closed (rule G2).
    pub complete: bool,
    /// Whether it is opaque (rules D6, D7).
    pub opaque: bool,
    /// Whether it is untrusted (rule D6).
    pub untrusted: bool,
    /// Its status (rule S2); `None` for a complete node.
    pub status: Option<NodeStatus>,
    /// Its `.holds` keys; empty for an opaque node (rule T2).
    pub holds: BTreeSet<String>,
    /// Its `.meters` claims; empty for an opaque node.
    pub meters: Vec<MeterClaim>,
}

/// An edge `(from, to)`: `from` must be complete before `to` is correct.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Edge {
    /// The prerequisite.
    pub from: IssueRef,
    /// The dependent.
    pub to: IssueRef,
}

/// The graph of a run, its readiness and the lists rule W1 reports.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Graph {
    /// The nodes (rule G1).
    pub nodes: BTreeMap<IssueRef, Node>,
    /// The containers, with their children in written order (rules D9, W1).
    pub containers: BTreeMap<IssueRef, Vec<IssueRef>>,
    /// The unmodeled issues (rule D7).
    pub unmodeled: BTreeSet<IssueRef>,
    /// Every issue that is not admitted (rules D6, W1).
    pub untrusted: BTreeSet<IssueRef>,
    /// The numbers of the pull requests that close an issue and are not
    /// admitted (rules AD9, W1).
    pub untrusted_pull_requests: BTreeSet<u64>,
    /// The edges of the graph (rule G3), redundant ones included.
    pub edges: BTreeSet<Edge>,
    /// The satisfied edges: each completed prerequisite of an open task.
    pub satisfied: BTreeSet<Edge>,
    /// The satisfied edges whose prerequisite was closed as `not_planned`.
    pub not_planned: BTreeSet<Edge>,
    /// The edges the reduction removes (rule G5).
    pub redundant: BTreeSet<Edge>,
    /// The ready set (rule Q1), unordered: its rank order is rule K6's.
    pub ready: BTreeSet<IssueRef>,
}

impl Graph {
    /// The dispatchable subset of the ready set (rule Q2).
    #[must_use]
    pub fn dispatchable(&self) -> BTreeSet<IssueRef> {
        self.ready
            .iter()
            .filter(|id| {
                self.nodes.get(*id).is_some_and(|n| {
                    !n.opaque && !n.untrusted && n.status != Some(NodeStatus::Blocked)
                })
            })
            .cloned()
            .collect()
    }
}

/// Why a run is rejected (profile rule I2).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Rejection {
    /// The trust policy is not `taskalisk/threat-model`.
    UnknownPolicy(String),
    /// A root is not a reference under format rule L1.
    RootNotAReference(String),
    /// A root is in a repository outside the read scope.
    RootOutsideScope(IssueRef),
}

/// The outcome of a run (profile rule F1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Outcome {
    /// A run parameter is invalid.
    Rejected(Rejection),
    /// A required observation is unavailable; no graph (rule F2).
    Incomplete {
        /// Why the observation was unavailable, as recorded.
        unavailable: String,
    },
    /// Some rule fails. The graph is reported for diagnosis (rule F3) unless
    /// the edges could not all be resolved (X3) or form a cycle (G4).
    Invalid {
        /// The findings, warnings included.
        findings: BTreeSet<Finding>,
        /// The graph, for diagnosis only.
        graph: Option<Graph>,
    },
    /// A plan.
    Planned {
        /// The findings: warnings only.
        findings: BTreeSet<Finding>,
        /// The graph.
        graph: Graph,
    },
}

/// Plans over the observations a forge answers with.
///
/// # Errors
///
/// [`Missing`] when the run reads an observation that was not recorded.
pub const fn plan<F: Forge + ?Sized>(
    _parameters: &Parameters,
    _forge: &F,
) -> Result<Outcome, Missing> {
    Err(Missing {
        what: String::new(),
    })
}
