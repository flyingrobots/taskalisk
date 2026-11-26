//! Findings of one document (flyingrobots/taskalisk#43).
//!
//! A [`Finding`] states one violation or warning of a document judgement
//! ([`crate::admit`]) as a stable code, a severity, a subject and a message.
//!
//! The codes are tabled on [`code`].

use crate::label::Label;
use crate::reference::IssueRef;
use crate::{Judgement, admit};

/// Every label a document judgement can carry, in the order of its text.
/// Each label stands at its position (checked when the crate compiles).
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
    /// A warning (rule V10): validity is unaffected.
    Warning,
}

impl Severity {
    /// `"error"` or `"warning"`.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Error => "error",
            Self::Warning => "warning",
        }
    }
}

/// One violation or warning of a document.
///
/// The subject is the address of the issue that holds the document, never
/// the document's own `.id` (a `.id` that differs is finding `profile.X1`). A message is fixed text for its code:
/// it may name a key, and never carries a value or a line of the body.
/// The fields are in sort order: findings sort by subject, then code, so two
/// runs give the same report.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Finding {
    /// The address of the issue that holds the document.
    pub subject: IssueRef,
    /// The stable code (see the table on [`code`]).
    pub code: &'static str,
    /// Error for a violation, warning for the advisory.
    pub severity: Severity,
    /// Fixed text for the code. It may name a key, never a value or a line.
    pub message: &'static str,
}

/// The index of a label in [`LABELS`]. The match is exhaustive, so a new
/// label cannot be added without a place in the list.
const fn position(label: Label) -> usize {
    match label {
        Label::C4 => 0,
        Label::C6 => 1,
        Label::C7 => 2,
        Label::C8 => 3,
        Label::L1 => 4,
        Label::L2 => 5,
        Label::L3 => 6,
        Label::L4 => 7,
        Label::P3 => 8,
        Label::V1 => 9,
        Label::V10 => 10,
        Label::V2 => 11,
        Label::V3 => 12,
        Label::V4 => 13,
        Label::V5 => 14,
        Label::V6 => 15,
        Label::V7 => 16,
        Label::V8 => 17,
        Label::X1 => 18,
    }
}

// LABELS holds each label at its position.
const _: () = {
    let mut i = 0;
    while i < LABELS.len() {
        assert!(
            position(LABELS[i]) == i,
            "LABELS is out of step with position"
        );
        i += 1;
    }
};

/// The stable code of a label.
///
/// A code is `<document>.<label>`: the label of the rule, as format rule V12
/// assigns it, prefixed by the specification that states the rule.
/// `format.` is the format `issue-dag/2` (carrier rules C, value rules L,
/// validity rules V), `version.` the version policy (rule P3), and `profile.`
/// the planning profile `issue-dag-planning/2` (rule X1). A code never
/// changes meaning; a rule that is added gets a new code.
///
/// Rules C1 to C3 decide whether a body has a document at all (a body without
/// one has no findings), and C5, C9, C10, V9, V11 and V12 never fail a
/// document, so they have no code. A `.dag` string other than `issue-dag/2`
/// is `version.P3` when it names a format (`issue-dag/N`) and `format.V1`
/// otherwise (V12).
///
/// | Code | Rule | Severity |
/// | --- | --- | --- |
/// | `format.C4` | a line break the carrier does not allow | error |
/// | `format.C6` | a line that is not an entry line | error |
/// | `format.C7` | a duplicate key | error |
/// | `format.C8` | a list value that does not end with `]` | error |
/// | `format.L1` | a string that is not a reference | error |
/// | `format.L2` | an empty resource key | error |
/// | `format.L3` | an item that is not a meter claim | error |
/// | `format.L4` | a `.size_hours` out of bounds | error |
/// | `version.P3` | a `.dag` naming another format version | error |
/// | `format.V1` | an absent or malformed `.dag` | error |
/// | `format.V10` | a `.size_hours` above 8 | warning |
/// | `format.V2` | an unknown format key | error |
/// | `format.V3` | an absent `.id`, or one that is not a string | error |
/// | `format.V4` | an absent or wrong `.kind` | error |
/// | `format.V5` | a task's keys | error |
/// | `format.V6` | a container's keys | error |
/// | `format.V7` | a self reference | error |
/// | `format.V8` | an optional key | error |
/// | `profile.X1` | a `.id` that is not the issue's address | error |
#[must_use]
pub const fn code(label: Label) -> &'static str {
    match label {
        Label::C4 => "format.C4",
        Label::C6 => "format.C6",
        Label::C7 => "format.C7",
        Label::C8 => "format.C8",
        Label::L1 => "format.L1",
        Label::L2 => "format.L2",
        Label::L3 => "format.L3",
        Label::L4 => "format.L4",
        Label::P3 => "version.P3",
        Label::V1 => "format.V1",
        Label::V10 => "format.V10",
        Label::V2 => "format.V2",
        Label::V3 => "format.V3",
        Label::V4 => "format.V4",
        Label::V5 => "format.V5",
        Label::V6 => "format.V6",
        Label::V7 => "format.V7",
        Label::V8 => "format.V8",
        Label::X1 => "profile.X1",
    }
}

/// The message of a label: fixed text that names keys and rules only.
const fn message(label: Label) -> &'static str {
    match label {
        Label::C4 => {
            "the frontmatter block holds a line break the carrier does not allow (a CR without LF, \
             or U+000B, U+000C, U+001C to U+001E, U+0085, U+2028 or U+2029); no other rule was \
             applied"
        }
        Label::C6 => "a line of the frontmatter block is not an entry line, a comment or blank",
        Label::C7 => "two entry lines of the frontmatter block have the same key",
        Label::C8 => "a list value does not end with ]",
        Label::L1 => "a value that must be a reference is not of the form owner/repo#N",
        Label::L2 => "an item of .holds is an empty resource key",
        Label::L3 => "an item of .meters is not a meter claim (name or name*N)",
        Label::L4 => ".size_hours is not between 1 and 2147483647",
        Label::P3 => {
            ".dag names a format version other than issue-dag/2; issue-dag/1 is retired: write \
             every reference as owner/repo#N and set .dag to issue-dag/2"
        }
        Label::V1 => ".dag is absent or is not the string issue-dag/2",
        Label::V10 => ".size_hours is above 8: the task is probably not atomic",
        Label::V2 => "a format key is not a key of issue-dag/2",
        Label::V3 => ".id is absent or is not a string",
        Label::V4 => ".kind is absent or is neither task nor container",
        Label::V5 => {
            "a task needs .type from the task types and .blocked_by as a list of references, and \
             no .children"
        }
        Label::V6 => {
            "a container needs .children as a list of references and no .blocked_by, and a .type, \
             if present, from the task types"
        }
        Label::V7 => ".blocked_by or .children names the document's own .id",
        Label::V8 => ".size_hours, .holds, .meters or .status has a value of the wrong kind",
        Label::X1 => ".id is not the address of the issue that holds the document",
    }
}

/// The findings of a body held by the issue at `address`, sorted by code.
///
/// The body is judged with its address ([`crate::admit`]), so profile rule X1
/// always applies, and every finding's subject is the address. A body
/// without a document and a valid document without warnings have none.
#[must_use]
pub fn findings(body: &str, address: &IssueRef) -> Vec<Finding> {
    match admit(body, Some(address)) {
        Judgement::NoDocument => Vec::new(),
        Judgement::Valid { warnings, .. } => from_labels(address, &warnings, Severity::Warning),
        Judgement::Invalid(validation) => {
            from_labels(address, &validation.violations, Severity::Error)
        }
    }
}

/// One finding per label, under one subject, sorted by code.
fn from_labels<'a>(
    subject: &IssueRef,
    labels: impl IntoIterator<Item = &'a Label>,
    severity: Severity,
) -> Vec<Finding> {
    let mut found: Vec<Finding> = labels
        .into_iter()
        .map(|&label| Finding {
            subject: subject.clone(),
            code: code(label),
            severity,
            message: message(label),
        })
        .collect();
    found.sort();
    found
}

#[cfg(test)]
mod tests {
    use super::{LABELS, Severity, from_labels, position};
    use crate::label::Label;
    use crate::reference::IssueRef;

    /// LABELS lists every label once, in the order `position` gives; the
    /// match in `position` is exhaustive, so a new label must be placed.
    #[test]
    fn labels_lists_every_label_at_its_position() {
        for (i, label) in LABELS.iter().enumerate() {
            assert_eq!(position(*label), i, "{label}");
        }
        assert_eq!(position(Label::X1) + 1, LABELS.len());
    }

    /// Label order is not code order: `version.P3` sits between `format.L4`
    /// and `format.V1` as a label, after every `format.` code as a code.
    #[test]
    fn findings_come_out_in_code_text_order() {
        let subject = IssueRef::parse("o/r#1").expect("a reference");
        let found = from_labels(&subject, &[Label::P3, Label::V1], Severity::Error);
        let codes: Vec<&str> = found.iter().map(|f| f.code).collect();
        assert_eq!(codes, ["format.V1", "version.P3"]);
    }
}
