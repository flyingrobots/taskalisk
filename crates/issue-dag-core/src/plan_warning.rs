//! Plan warnings (flyingrobots/taskalisk#61).
//!
//! Taskalisk's own advisories about a plan as a whole, from the skill's
//! doctrine on graph health (`skills/taskalisk/SKILL.md`, Core Doctrine 4).
//! A plan warning concerns no single issue, so it is not a [`Finding`]
//! (which always has a subject): it is a [`PlanWarning`], beside the
//! findings, with a catalogued [`Code`] and a detail of what it measured.
//! It never makes a run invalid. [`plan_warnings`] reads them from a
//! [`Graph`] that [`crate::plan`] returned.
//!
//! [`Finding`]: crate::Finding

use crate::finding::{Code, Severity};
use crate::plan::Graph;

/// The code of the edge-density warning.
const EDGE_DENSITY: &str = "taskalisk.edge-density";

/// The band of edge density the skill states, both ends included: the
/// Python compiler's `DENSITY_BAND`.
pub const DENSITY_BAND: (f64, f64) = (0.01, 0.50);

/// Every plan warning's code, once each, in the order of its text.
pub const PLAN_WARNINGS: [&str; 1] = [EDGE_DENSITY];

/// The codes of [`PLAN_WARNINGS`] with their severity, in its order: this
/// family's entry in [`crate::CODES`].
pub const PLAN_CODES: [(&str, Severity); PLAN_WARNINGS.len()] = [(EDGE_DENSITY, Severity::Warning)];

/// What a plan warning measured.
#[derive(Clone, Copy, Debug, PartialEq)]
#[non_exhaustive]
pub enum PlanDetail {
    /// The plan's edge density and the band it falls outside.
    Density {
        /// The edges of the reduced graph: the graph's edges less the
        /// redundant ones (G5).
        reduced_edges: usize,
        /// The open nodes.
        open_nodes: usize,
        /// `reduced_edges / (open_nodes * (open_nodes - 1) / 2)`, rounded
        /// to four decimal places, as the Python compiler rounds it.
        density: f64,
        /// The band, [`DENSITY_BAND`].
        band: (f64, f64),
    },
}

/// A warning about a plan as a whole: a catalogued code, its severity, a
/// fixed message and what it measured.
#[derive(Clone, Debug, PartialEq)]
pub struct PlanWarning {
    /// The stable code, an entry of [`crate::CODES`]; read with
    /// [`PlanWarning::code`].
    code: Code,
    /// Fixed text for the code. It never carries issue text.
    pub message: &'static str,
    /// What it measured.
    pub detail: PlanDetail,
}

impl PlanWarning {
    /// The stable code, an entry of [`crate::CODES`].
    #[must_use]
    pub const fn code(&self) -> Code {
        self.code
    }

    /// The severity of its code, [`Code::severity`]: a warning.
    #[must_use]
    pub const fn severity(&self) -> Severity {
        self.code.severity()
    }
}

/// The plan warnings of a plan's graph, in code order.
///
/// - `taskalisk.edge-density`, once, when the graph has more than one open
///   node and its edge density, rounded to four decimal places, is outside
///   [`DENSITY_BAND`]. The density is the number of reduced edges over the
///   number of pairs of open nodes, as the Python compiler computes it.
#[must_use]
pub fn plan_warnings(graph: &Graph) -> Vec<PlanWarning> {
    let Some(density) = edge_density(graph) else {
        return Vec::new();
    };
    let open_nodes = open_nodes(graph);
    let reduced_edges = reduced_edges(graph);
    let (low, high) = DENSITY_BAND;
    if (low..=high).contains(&density) {
        return Vec::new();
    }
    vec![PlanWarning {
        code: Code::of(EDGE_DENSITY),
        message: "the plan's edge density is outside the band 0.01 to 0.50: edges may be \
                  unrecorded (below) or over-declared (above)",
        detail: PlanDetail::Density {
            reduced_edges,
            open_nodes,
            density,
            band: DENSITY_BAND,
        },
    }]
}

/// A plan's edge density: the edges of its reduced graph (its edges less
/// the redundant ones, G5) over the pairs of its open nodes,
/// `n(n-1)/2`, rounded to four decimal places. `None` with fewer than two
/// open nodes, which have no pairs. Both [`plan_warnings`] and the
/// renderer's `edge_density` metric read it, as the Python compiler's
/// `edge_density`.
#[must_use]
pub fn edge_density(graph: &Graph) -> Option<f64> {
    let open_nodes = open_nodes(graph);
    if open_nodes < 2 {
        return None;
    }
    let pairs = open_nodes * (open_nodes - 1) / 2;
    Some(round4(ratio(reduced_edges(graph), pairs)))
}

/// The open nodes of `graph`.
fn open_nodes(graph: &Graph) -> usize {
    graph.nodes.values().filter(|n| !n.complete).count()
}

/// The edges of `graph`'s reduced graph.
fn reduced_edges(graph: &Graph) -> usize {
    graph.edges.difference(&graph.redundant).count()
}

/// `a / b` as a float. Counts of nodes and edges are far below 2^52, so
/// the conversion is exact.
#[allow(clippy::cast_precision_loss)]
fn ratio(a: usize, b: usize) -> f64 {
    a as f64 / b as f64
}

/// `x` rounded to four decimal places.
fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}
