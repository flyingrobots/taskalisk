//! Body warnings (flyingrobots/taskalisk#48): Taskalisk's own convention
//! for a task body, `skills/taskalisk/WRITING-TASKS.md`. Not part of the
//! `issue-dag/2` format; the codes carry the prefix `taskalisk.`.

use crate::finding::{Finding, Severity};
use crate::reference::IssueRef;

/// Declares [`BodyWarning`], its code, its list [`BODY_WARNINGS`] and the
/// count from one list, so a variant cannot exist without its code. The list
/// is written in the order of the codes' text, which is the derived [`Ord`].
macro_rules! body_warnings {
    ($($(#[doc = $doc:literal])* $name:ident => $code:literal,)+) => {
        /// A sign that a task body departs from Taskalisk's writing
        /// convention. Each is a warning; none affects validity.
        #[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub enum BodyWarning {
            $($(#[doc = $doc])* $name,)+
        }

        impl BodyWarning {
            /// The stable code, such as `"taskalisk.outcome-missing"`
            /// (tabled on [`crate::code`]).
            #[must_use]
            pub const fn code(self) -> &'static str {
                match self {
                    $(Self::$name => $code,)+
                }
            }
        }

        /// The number of body warnings.
        const COUNT: usize = [$($code),+].len();

        /// Every body warning, once each, in the order of its code's text.
        pub const BODY_WARNINGS: [BodyWarning; COUNT] = [$(BodyWarning::$name),+];
    };
}

body_warnings! {
    /// No `## Acceptance` heading.
    AcceptanceMissing => "taskalisk.acceptance-missing",
    /// The Outcome section has more than one list item.
    OutcomeItems => "taskalisk.outcome-items",
    /// No `## Outcome` heading.
    OutcomeMissing => "taskalisk.outcome-missing",
    /// The Outcome section has more than one sentence.
    OutcomeSentences => "taskalisk.outcome-sentences",
    /// No `## Scope` heading.
    ScopeMissing => "taskalisk.scope-missing",
    /// The title joins two things with `and` or a semicolon.
    TitleJoins => "taskalisk.title-joins",
}

/// The body warnings of a task. Not yet implemented.
#[must_use]
pub const fn body_warnings(_body: &str, _address: &IssueRef, _title: Option<&str>) -> Vec<Finding> {
    let _ = Severity::Warning;
    Vec::new()
}
