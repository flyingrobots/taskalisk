//! Renders a plan to the JSON result lines the Taskalisk skill reads.

use issue_dag_core::{Outcome, Parameters};

/// Why a run has no result lines.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NotRendered {
    /// The run was rejected.
    Rejected,
    /// A required observation was unavailable.
    Incomplete,
}

/// The result lines of a plan.
///
/// # Errors
///
/// [`NotRendered`] when the run has no result lines.
pub fn render(_parameters: &Parameters, _outcome: &Outcome) -> Result<String, NotRendered> {
    Ok(String::new())
}
