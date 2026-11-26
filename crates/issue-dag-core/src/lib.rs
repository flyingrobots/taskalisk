//! The `issue-dag/2` document core.
//!
//! A hand-written reader for the `issue-dag/2` format: the carrier
//! ([`parse`]), validity ([`validate`]), the decoded record ([`admit`]), and
//! the `.blocked_by` rewrite of the edge-edit contract ([`rewrite_blocked_by`]),
//! and a planning run under `issue-dag-planning/2` ([`plan`]) over the
//! observations a [`Forge`] answers with, admission included, with the
//! ranking of its graph ([`rank`]) and its batch ([`select`]).
//! A body becomes findings with stable codes ([`findings`]); the codes
//! are tabled on [`code`]. A task body also gets Taskalisk's own body
//! warnings ([`body_warnings`]).
//! The crate performs no I/O and depends only on `pulldown-cmark`.
mod admission;
mod batch;
mod body;
mod carrier;
mod finding;
mod forge;
mod label;
mod local;
mod observation;
mod plan;
mod rank;
mod record;
mod reference;
mod rewrite;
mod validate;

use std::collections::BTreeSet;

pub use admission::{Admission, Identity, Undecided, codeowners_persons};
pub use batch::{Batch, Skip, keys_conflict, select};
pub use body::{BODY_WARNINGS, BodyWarning, body_warnings};
pub use carrier::{Block, Entry, Integer, Parse, Slot, Value, parse, trim};
pub use finding::{CODES, Finding, LABELS, PROFILE_RULES, Rule, Severity, code, findings};
pub use forge::{Bundle, Forge, LocalRepository, NoLocalRepository, Observations, RecordedForge};
pub use label::Label;
pub use local::{AheadBehind, Branch, BranchScope, Checkout, Worktree};
pub use observation::{
    Actor, Body, CodeownersFile, Issue, IssueState, Lookup, Missing, Observed, Parameters,
    PullRequest, ReadScope, Repo, TRUST_POLICY, TrustParameters,
};
pub use plan::{Edge, Graph, Node, NodeStatus, Outcome, Rejection, plan};
pub use rank::{Ranking, rank};
pub use record::{Kind, MeterClaim, Record, Status, TaskType, VERSION};
pub use reference::{IssueRef, MAX_NUMBER, is_name};
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
    judge(&parse(body), address)
}

/// [`admit`] for a body already parsed, so a caller that also reads the
/// parse does not parse the same text twice.
pub(crate) fn judge(parsed: &Parse, address: Option<&IssueRef>) -> Judgement {
    match parsed {
        Parse::NoDocument => Judgement::NoDocument,
        Parse::Unreadable => Judgement::Invalid(Validation {
            violations: BTreeSet::from([Label::C4]),
            warnings: BTreeSet::new(),
        }),
        Parse::Block(block) => match validate::decode(block, address) {
            (validation, Some(record)) if validation.violations.is_empty() => Judgement::Valid {
                record,
                warnings: validation.warnings,
            },
            (validation, _) => Judgement::Invalid(validation),
        },
    }
}
