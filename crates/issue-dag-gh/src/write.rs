//! The forge write port through `gh` (flyingrobots/taskalisk#1): the
//! account a write is made as (`gh api user`) and the one write an edge edit
//! makes, the replacement of an issue body (`gh api -X PATCH`).

use core::fmt;

use issue_dag_core::{Actor, ForgeWrite, IssueRef, Observed};

use crate::GhForge;

/// A write through `gh` that failed: `gh.mutation_failed`. The request may
/// have been applied before the failure, so whether the body changed is
/// unknown; it is reported, never retried or undone (edge-edit rule E9).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WriteFailure {
    /// The request, such as `gh api -X PATCH repos/o/r/issues/1`.
    pub source: String,
    /// What `gh` said, scrubbed of secrets and the home directory.
    pub detail: String,
}

impl WriteFailure {
    /// The stable code of the failure.
    pub const CODE: &'static str = "gh.mutation_failed";
}

impl fmt::Display for WriteFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.source, self.detail)
    }
}

impl std::error::Error for WriteFailure {}

impl ForgeWrite for GhForge {
    type Error = WriteFailure;

    fn writer(&self) -> Observed<Actor> {
        unimplemented!("flyingrobots/taskalisk#1")
    }

    fn replace_body(&self, issue: &IssueRef, body: &str) -> Result<(), WriteFailure> {
        let _ = (issue, body);
        unimplemented!("flyingrobots/taskalisk#1")
    }
}
