//! The `issue-dag/2` document core.
//!
//! A hand-written reader for the `issue-dag/2` format: the carrier
//! ([`parse`]), validity ([`validate`]), the decoded record ([`admit`]), and
//! the `.blocked_by` rewrite of the edge-edit contract ([`rewrite_blocked_by`]).
//! The crate performs no I/O and has no dependencies.
mod carrier;
mod label;
mod record;
mod reference;
mod rewrite;
mod validate;

use std::collections::BTreeSet;

pub use carrier::{Block, Entry, Integer, Parse, Value, parse, trim};
pub use label::Label;
pub use record::{Kind, MeterClaim, Record, Status, TaskType, VERSION};
pub use reference::{IssueRef, MAX_NUMBER};
pub use rewrite::{EdgeEdit, Refusal, Rewrite, rewrite_blocked_by};
pub use validate::{Validation, validate};

/// The judgement of one body.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Judgement {
    /// The body has no frontmatter block (rule C3).
    NoDocument,
    /// A valid document, its record and its warnings.
    Valid {
        /// The decoded record (rule M4).
        record: Record,
        /// The labels of its warnings (rule V10).
        warnings: BTreeSet<Label>,
    },
    /// An invalid document.
    Invalid(Validation),
}

/// Reads a body and judges it: no document, a valid document with its
/// record, or an invalid document with its violations. With an address,
/// `.id` is also judged under profile rule X1.
#[must_use]
pub fn admit(body: &str, address: Option<&IssueRef>) -> Judgement {
    match parse(body) {
        Parse::NoDocument => Judgement::NoDocument,
        Parse::Unreadable => Judgement::Invalid(Validation {
            violations: BTreeSet::from([Label::C4]),
            warnings: BTreeSet::new(),
        }),
        Parse::Block(block) => match validate::decode(&block, address) {
            (validation, Some(record)) if validation.violations.is_empty() => Judgement::Valid {
                record,
                warnings: validation.warnings,
            },
            (validation, _) => Judgement::Invalid(validation),
        },
    }
}
