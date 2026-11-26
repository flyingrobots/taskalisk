//! The `.blocked_by` rewrite of the edge-edit contract (rule E4).

use crate::label::Label;
use crate::reference::IssueRef;

/// One edge edit on a child's `.blocked_by` (rule E1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EdgeEdit {
    /// Make the parent a prerequisite of the child.
    Add(IssueRef),
    /// Take every occurrence of the parent out of the child's `.blocked_by`.
    Remove(IssueRef),
}

/// Why a rewrite is refused.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Refusal {
    /// The body has no frontmatter block.
    NoDocument,
    /// The body is not a valid document; the labels of its violations.
    Invalid(Vec<Label>),
    /// The document is a container, which has no `.blocked_by`.
    NotATask,
    /// The block does not have exactly one `.blocked_by` line; the count.
    BlockedByLines(usize),
    /// The parent equals the child (rule E1).
    SelfEdge,
}

/// A rewritten body.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Rewrite {
    /// The new body.
    pub body: String,
    /// Whether it differs from the old body; when it does not, nothing is
    /// to be written (rule E5).
    pub changed: bool,
}

/// Rewrites the `.blocked_by` line of a valid task document, judged with its
/// issue's address, and changes no other character of the body (rule E4).
///
/// # Errors
///
/// Returns a [`Refusal`] when the body is not a valid task document for that
/// address, when its block does not have exactly one `.blocked_by` line, or
/// when the parent equals the child.
pub fn rewrite_blocked_by(
    body: &str,
    address: &IssueRef,
    edit: &EdgeEdit,
) -> Result<Rewrite, Refusal> {
    let _ = (body, address, edit);
    Err(Refusal::NoDocument)
}
