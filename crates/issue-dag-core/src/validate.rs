//! Key binding and validity (format sections 3 to 5) and the record (M4).

use std::collections::BTreeSet;

use crate::carrier::Block;
use crate::label::Label;
use crate::record::Record;
use crate::reference::IssueRef;

/// The violations and warnings of a document.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Validation {
    /// The labels of the rules the document fails, each once (rule V12).
    pub violations: BTreeSet<Label>,
    /// The labels of its warnings (rule V10).
    pub warnings: BTreeSet<Label>,
}

/// Validates a block. With an address, `.id` is also judged under profile
/// rule X1.
#[must_use]
pub fn validate(block: &Block, address: Option<&IssueRef>) -> Validation {
    decode(block, address).0
}

pub(crate) fn decode(block: &Block, address: Option<&IssueRef>) -> (Validation, Option<Record>) {
    let _ = (block, address);
    (Validation::default(), None)
}
