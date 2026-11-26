//! Findings of one document (flyingrobots/taskalisk#43).

use crate::Judgement;
use crate::label::Label;
use crate::reference::IssueRef;

/// Every label a document judgement can carry.
pub const LABELS: [Label; 19] = [
    Label::C4,
    Label::C6,
    Label::C7,
    Label::C8,
    Label::L1,
    Label::L2,
    Label::L3,
    Label::L4,
    Label::P3,
    Label::V1,
    Label::V10,
    Label::V2,
    Label::V3,
    Label::V4,
    Label::V5,
    Label::V6,
    Label::V7,
    Label::V8,
    Label::X1,
];

/// How much a finding matters.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Severity {
    /// A violation: the document is invalid.
    Error,
    /// A warning: validity is unaffected.
    Warning,
}

/// One thing a reader must see about a document.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Finding {
    /// The issue the finding is about.
    pub subject: IssueRef,
    /// The stable code.
    pub code: &'static str,
    /// Error or warning.
    pub severity: Severity,
    /// The message.
    pub message: &'static str,
}

/// The stable code of a label.
#[must_use]
pub const fn code(_label: Label) -> &'static str {
    ""
}

/// The findings of a document judgement.
#[must_use]
pub const fn findings(_judgement: &Judgement, _address: &IssueRef) -> Vec<Finding> {
    Vec::new()
}
