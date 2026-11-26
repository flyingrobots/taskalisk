//! Findings of a document (flyingrobots/taskalisk#43) and of a planning run
//! (flyingrobots/taskalisk#28).
//!
//! A [`Finding`] states one violation or warning, of a document judgement
//! ([`crate::admit`]) or of a run ([`crate::plan`]), as a stable code, a
//! severity, a subject, the reference it concerns when its rule has one, and
//! a message. One type serves both, because profile rule F5 gives a run's
//! findings the document's labels and identifies every finding the same way.
//!
//! The codes are tabled on [`code`] and [`Rule::code`], and listed, with
//! every other family of findings, in the catalogue [`CODES`].

use core::fmt;

use crate::body::BODY_CODES;
use crate::label::{self, Label};
use crate::observation::NotFound;
use crate::plan_warning::PLAN_CODES;
use crate::reference::IssueRef;
use crate::shape::SHAPE_CODES;
use crate::{Judgement, admit};

/// Every label a document judgement can carry, once each, in the order of
/// its text. Declared with [`Label`] itself, so no label can be missing.
pub const LABELS: [Label; label::VARIANTS] = label::ALL;

/// The catalogue of every finding code the crate can report.
///
/// Each code comes with its severity: the document codes in [`LABELS`] order, then the planning
/// profile's in [`PROFILE_RULES`] order, then the causes of a reference not found
/// ([`NotFound::code`], in [`NotFound::ALL`] order), then Taskalisk's body warnings in
/// [`crate::BODY_WARNINGS`] order, then its shape warnings in [`crate::SHAPE_WARNINGS`] order,
/// then its plan warnings in [`crate::PLAN_WARNINGS`] order.
/// Each code appears once.
///
/// This is the one public source of the codes; the table on [`code`] and
/// any reference page are checked against it. Every family of findings must
/// register its codes here: a family supplies an array of its codes with
/// their severities, and registers it with one line in `FAMILIES` (in this module).
pub const CODES: &[(&str, Severity)] = &CATALOGUE;

/// Each family's codes with their severities, in catalogue order. A new
/// family of findings is one more line here.
const FAMILIES: &[&[(&str, Severity)]] = &[
    &LABEL_CODES,
    &PROFILE_CODES,
    &NOT_FOUND_CODES,
    &BODY_CODES,
    &SHAPE_CODES,
    &PLAN_CODES,
];

/// The document codes in [`LABELS`] order, with [`Rule::severity`].
const LABEL_CODES: [(&str, Severity); LABELS.len()] = {
    let mut out = [("", Severity::Error); LABELS.len()];
    let mut i = 0;
    while i < LABELS.len() {
        let rule = Rule::Document(LABELS[i]);
        out[i] = (rule.code(), rule.severity());
        i += 1;
    }
    out
};

/// The planning profile's codes in [`PROFILE_RULES`] order, with
/// [`Rule::severity`].
const PROFILE_CODES: [(&str, Severity); PROFILE_RULES.len()] = {
    let mut out = [("", Severity::Error); PROFILE_RULES.len()];
    let mut i = 0;
    while i < PROFILE_RULES.len() {
        out[i] = (PROFILE_RULES[i].code(), PROFILE_RULES[i].severity());
        i += 1;
    }
    out
};

/// The causes of a reference not found (profile rules D11 to D13), in
/// [`NotFound::ALL`] order. A cause is no finding: an incomplete run reports
/// it beside its reason ([`crate::Outcome::Incomplete`]), and it has a code
/// so that the report is stable.
const NOT_FOUND_CODES: [(&str, Severity); NotFound::ALL.len()] = {
    let mut out = [("", Severity::Error); NotFound::ALL.len()];
    let mut i = 0;
    while i < NotFound::ALL.len() {
        out[i] = (not_found_code(NotFound::ALL[i]), Severity::Error);
        i += 1;
    }
    out
};

/// The code text of a cause: `profile.` and the label of its rule.
const fn not_found_code(cause: NotFound) -> &'static str {
    match cause {
        NotFound::Owner => "profile.D11",
        NotFound::Repository => "profile.D12",
        NotFound::Number => "profile.D13",
    }
}

impl NotFound {
    /// The catalogued code of the cause: `profile.D11`, `profile.D12` or
    /// `profile.D13`.
    #[must_use]
    pub const fn code(self) -> Code {
        Code::of(not_found_code(self))
    }
}

/// The number of codes over all [`FAMILIES`].
const CODE_COUNT: usize = {
    let mut total = 0;
    let mut f = 0;
    while f < FAMILIES.len() {
        total += FAMILIES[f].len();
        f += 1;
    }
    total
};

/// [`CODES`] as an array: the [`FAMILIES`] concatenated in order.
const CATALOGUE: [(&str, Severity); CODE_COUNT] = {
    let mut out = [("", Severity::Error); CODE_COUNT];
    let mut k = 0;
    let mut f = 0;
    while f < FAMILIES.len() {
        let family = FAMILIES[f];
        let mut i = 0;
        while i < family.len() {
            out[k] = family[i];
            k += 1;
            i += 1;
        }
        f += 1;
    }
    out
};

/// A finding code: an entry of the catalogue [`CODES`].
///
/// It has no public constructor. The crate builds a `Code` only by finding
/// its text in the catalogue, so every finding carries a catalogued code, and
/// a family of findings that does not register its codes in [`CODES`] cannot
/// emit them. Its text ([`Code::as_str`], also its [`fmt::Display`] and
/// [`fmt::Debug`] form) is the code as reports print it; codes compare and
/// order as their text. Its severity is the catalogue's ([`Code::severity`]),
/// the one place each code's severity is defined.
///
/// ```compile_fail
/// let invented = issue_dag_core::Code(0);
/// ```
///
/// Nor is there a public way to build one from text:
///
/// ```compile_fail
/// let found = issue_dag_core::Code::of("format.V1");
/// ```
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct Code(usize);

impl Code {
    /// The catalogued code whose text is `text`.
    ///
    /// # Panics
    ///
    /// If `text` is in no catalogue entry. Every emitter takes its text from
    /// a family that [`CODES`] is built from, so this does not happen.
    pub(crate) const fn of(text: &str) -> Self {
        let mut i = 0;
        while i < CATALOGUE.len() {
            if same_text(CATALOGUE[i].0, text) {
                return Self(i);
            }
            i += 1;
        }
        panic!("a finding code that is not in the catalogue CODES");
    }

    /// The code's text, such as `"format.V1"`.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        CATALOGUE[self.0].0
    }

    /// The code's severity, as the catalogue gives it.
    #[must_use]
    pub const fn severity(self) -> Severity {
        CATALOGUE[self.0].1
    }

    /// Every catalogued code, once each, in [`CODES`] order.
    pub fn all() -> impl Iterator<Item = Self> {
        (0..CATALOGUE.len()).map(Self)
    }
}

/// Whether two strings are equal, in a constant.
const fn same_text(a: &str, b: &str) -> bool {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    if a.len() != b.len() {
        return false;
    }
    let mut i = 0;
    while i < a.len() {
        if a[i] != b[i] {
            return false;
        }
        i += 1;
    }
    true
}

impl PartialOrd for Code {
    fn partial_cmp(&self, other: &Self) -> Option<core::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Code {
    fn cmp(&self, other: &Self) -> core::cmp::Ordering {
        self.as_str().cmp(other.as_str())
    }
}

impl PartialEq<&str> for Code {
    fn eq(&self, other: &&str) -> bool {
        self.as_str() == *other
    }
}

impl PartialEq<str> for Code {
    fn eq(&self, other: &str) -> bool {
        self.as_str() == other
    }
}

impl fmt::Display for Code {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl fmt::Debug for Code {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Debug::fmt(self.as_str(), f)
    }
}

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

/// One violation or warning: of a document, or of a planning run.
///
/// It is identified as profile rule F5 identifies a finding: the issue that
/// receives it, its rule (here as a stable code, whose suffix is the rule's
/// label), and for D3, D5, X2 and X3 the reference it concerns. Severity and
/// message follow from the code.
///
/// For a document finding, the subject is the address of the issue that
/// holds the document, never the document's own `.id` (a `.id` that differs
/// is finding `profile.X1`), and `concerns` is `None`. A message is fixed
/// text for its code: it may name a key or a rule, and never carries a
/// value, a reference or a line of the body; the one reference a finding
/// publishes is `concerns`, which profile rule T1 allows.
/// Equality, order and hash follow that identity alone: findings sort by
/// subject, then code, then the reference concerned, so two runs give the
/// same report, and a finding with other wording is the same finding.
///
/// Its code is a [`Code`], which only the catalogue builds, so no emitter can
/// give a finding a code that is in no catalogue:
///
/// ```compile_fail
/// use issue_dag_core::{Finding, IssueRef, Severity};
///
/// let invented = Finding {
///     subject: IssueRef::parse("o/r#1").expect("a reference"),
///     code: "made.up",
///     concerns: None,
///     severity: Severity::Error,
///     message: "a code in no catalogue",
/// };
/// ```
///
/// Its code and severity are read with [`Finding::code`] and
/// [`Finding::severity`], and cannot be assigned, so the pair cannot be split:
/// a caller can neither give a finding a severity other than its code's, nor
/// change its code and keep the old severity.
///
/// ```compile_fail
/// use issue_dag_core::{Finding, IssueRef, Rule, Severity};
///
/// let mut found = Finding::new(IssueRef::parse("o/r#1").expect("a reference"), Rule::D4, None);
/// found.severity = Severity::Warning;
/// ```
///
/// ```compile_fail
/// use issue_dag_core::{Finding, IssueRef, Rule};
///
/// let mut found = Finding::new(IssueRef::parse("o/r#1").expect("a reference"), Rule::D4, None);
/// let other = Finding::new(IssueRef::parse("o/r#1").expect("a reference"), Rule::G4, None);
/// found.code = other.code;
/// ```
#[derive(Clone, Debug)]
pub struct Finding {
    /// The issue that receives it.
    pub subject: IssueRef,
    /// The stable code, an entry of [`CODES`]; read with [`Finding::code`].
    code: Code,
    /// The reference it concerns, for D3, D5, X2 and X3; otherwise `None`.
    pub concerns: Option<IssueRef>,
    /// The severity of its code, [`Code::severity`]; read with
    /// [`Finding::severity`].
    severity: Severity,
    /// Fixed text for the code. It may name a key, never a value or a line.
    pub message: &'static str,
}

impl Finding {
    /// Its identity under profile rule F5.
    const fn identity(&self) -> (&IssueRef, Code, Option<&IssueRef>) {
        (&self.subject, self.code, self.concerns.as_ref())
    }
}

impl PartialEq for Finding {
    fn eq(&self, other: &Self) -> bool {
        self.identity() == other.identity()
    }
}

impl Eq for Finding {}

impl PartialOrd for Finding {
    fn partial_cmp(&self, other: &Self) -> Option<core::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Finding {
    fn cmp(&self, other: &Self) -> core::cmp::Ordering {
        self.identity().cmp(&other.identity())
    }
}

impl core::hash::Hash for Finding {
    fn hash<H: core::hash::Hasher>(&self, state: &mut H) {
        self.identity().hash(state);
    }
}

impl Finding {
    /// The finding of `rule` for `subject`, about `concerns`.
    #[must_use]
    pub const fn new(subject: IssueRef, rule: Rule, concerns: Option<IssueRef>) -> Self {
        Self::coded(subject, Code::of(rule.code()), concerns, rule.message())
    }

    /// The finding of the catalogued `code` for `subject`, about `concerns`,
    /// with the code's severity.
    pub(crate) const fn coded(
        subject: IssueRef,
        code: Code,
        concerns: Option<IssueRef>,
        message: &'static str,
    ) -> Self {
        Self {
            subject,
            code,
            concerns,
            severity: code.severity(),
            message,
        }
    }

    /// The stable code, an entry of [`CODES`] (see the table on [`code`]).
    #[must_use]
    pub const fn code(&self) -> Code {
        self.code
    }

    /// The severity of its code, [`Code::severity`]: error for a violation,
    /// warning for the advisory and the body warnings.
    #[must_use]
    pub const fn severity(&self) -> Severity {
        self.severity
    }

    /// The label of its rule, as the corpus writes it: the code without its
    /// document prefix, such as `"X3"` for `profile.X3`.
    #[must_use]
    pub fn label(&self) -> &'static str {
        let code = self.code.as_str();
        code.split_once('.').map_or(code, |(_, label)| label)
    }
}

/// Declares [`Rule`], its profile variants' codes and messages, and
/// [`PROFILE_RULES`] from one list, so a variant cannot exist without its
/// code, its message and its entry.
macro_rules! profile_rules {
    ($($(#[doc = $doc:literal])* $name:ident => $message:literal,)+) => {
        /// The rule a finding fails (profile rule F5): a document's label
        /// (format rule V12, X1 included), or a rule of the planning profile
        /// that discovery and the graph apply.
        ///
        /// The admission rules (AD), the input rules (I) and the outcome rules
        /// (F) give no finding: an unavailable lookup makes the run
        /// incomplete, and an invalid parameter rejects it, with no findings
        /// (F2).
        #[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub enum Rule {
            /// A document's violation or warning.
            Document(Label),
            $($(#[doc = $doc])* $name,)+
        }

        /// Every rule of the planning profile that gives a finding of its
        /// own, once each, in the order of declaration.
        pub const PROFILE_RULES: [Rule; [$(stringify!($name)),+].len()] = [$(Rule::$name),+];

        impl Rule {
            /// The label as the specification writes it, such as `"X3"`.
            #[must_use]
            pub const fn as_str(self) -> &'static str {
                match self {
                    Self::Document(label) => label.as_str(),
                    $(Self::$name => stringify!($name),)+
                }
            }

            /// The stable code: [`code`] for a document's label, and
            /// `profile.<label>` for a rule of the planning profile. Every
            /// code is in the one table, on [`code`].
            #[must_use]
            pub const fn code(self) -> &'static str {
                match self {
                    Self::Document(label) => code(label),
                    $(Self::$name => concat!("profile.", stringify!($name)),)+
                }
            }

            const fn message(self) -> &'static str {
                match self {
                    Self::Document(label) => message(label),
                    $(Self::$name => $message,)+
                }
            }

            /// Warning for the advisory V10, error for every other rule.
            #[must_use]
            pub const fn severity(self) -> Severity {
                match self {
                    Self::Document(Label::V10) => Severity::Warning,
                    _ => Severity::Error,
                }
            }
        }
    };
}

profile_rules! {
    /// D3: a reference outside the read scope.
    D3 => "a reference names a repository outside the read scope; it was not read",
    /// D4: a reference to a pull request.
    D4 => "the reference resolves to a pull request, not an issue",
    /// D5: a transferred reference.
    D5 => "a reference names an issue that was transferred; name its new address",
    /// X2: a prerequisite that is a container.
    X2 => ".blocked_by of an open task names a container",
    /// X3: an unknown prerequisite.
    X3 => ".blocked_by of an open task names an issue that is neither a node nor a container",
    /// G4: a node of a cycle, or downstream of one.
    G4 => "the node is on a cycle of .blocked_by edges, or downstream of one",
}

impl fmt::Display for Rule {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// The stable code of a label.
///
/// A code is `<document>.<label>`: the label of the rule, as format rule V12
/// assigns it, prefixed by the specification that states the rule.
/// `format.` is the format `issue-dag/2` (carrier rules C, value rules L,
/// validity rules V), `version.` the version policy (rule P3), and `profile.`
/// the planning profile `issue-dag-planning/2` (rule X1, and the rules of a
/// run that [`Rule::code`] codes: D3, D4, D5, X2, X3 and G4). A code never
/// changes meaning; a rule that is added gets a new code. The table lists
/// the codes in [`CODES`] order: the labels' codes in [`LABELS`] order, then
/// the profile's in [`PROFILE_RULES`] order, then the causes of a reference
/// not found ([`NotFound::code`]: D11, D12 and D13, which are no findings but
/// the cause an incomplete run reports), then the body warnings, then the
/// shape warnings, then the plan warnings.
///
/// Rules C1 to C3 decide whether a body has a document at all (a body without
/// one has no findings), and C5, C9, C10, V9, V11 and V12 never fail a
/// document, so they have no code. A `.dag` string other than `issue-dag/2`
/// is `version.P3` when it names a format (`issue-dag/N`) and `format.V1`
/// otherwise (V12).
///
/// The table ends with Taskalisk's own body warnings
/// ([`crate::body_warnings`], flyingrobots/taskalisk#48): its writing
/// convention for a task body, `skills/taskalisk/WRITING-TASKS.md`, not a
/// rule of any specification. Their code is `taskalisk.<name>`, given by
/// [`crate::BodyWarning::code`], listed in [`crate::BODY_WARNINGS`]; they are
/// stable on the same terms.
/// After them come its shape warnings ([`crate::shape_warnings`],
/// flyingrobots/taskalisk#42): advisories on a plan's graph from the skill's
/// doctrine on graph health, `skills/taskalisk/SKILL.md`, coded
/// `taskalisk.<name>` by [`crate::ShapeWarning::code`] and listed in
/// [`crate::SHAPE_WARNINGS`].
/// After those come its plan warnings ([`crate::plan_warnings`],
/// flyingrobots/taskalisk#61): advisories on a plan as a whole from the
/// skill's doctrine on graph health, `skills/taskalisk/SKILL.md`. They are
/// [`crate::PlanWarning`]s, not findings, as they concern no single issue;
/// their codes are listed in [`crate::PLAN_WARNINGS`].
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
/// | `profile.D3` | a reference outside the read scope | error |
/// | `profile.D4` | a reference to a pull request | error |
/// | `profile.D5` | a transferred reference | error |
/// | `profile.X2` | a prerequisite that is a container | error |
/// | `profile.X3` | an unknown prerequisite | error |
/// | `profile.G4` | a node of a cycle, or downstream of one | error |
/// | `profile.D13` | the cause of an incomplete run: issue number not found | error |
/// | `profile.D11` | the cause of an incomplete run: owner not found | error |
/// | `profile.D12` | the cause of an incomplete run: repository not found | error |
/// | `taskalisk.acceptance-missing` | a task body without `## Acceptance` | warning |
/// | `taskalisk.outcome-items` | an Outcome of more than one list item | warning |
/// | `taskalisk.outcome-missing` | a task body without `## Outcome` | warning |
/// | `taskalisk.outcome-sentences` | an Outcome of more than one sentence | warning |
/// | `taskalisk.scope-missing` | a task body without `## Scope` | warning |
/// | `taskalisk.title-joins` | a title joining two things with "and" or `;` | warning |
/// | `taskalisk.isolated-task` | an open task with no edge in or out | warning |
/// | `taskalisk.redundant-edge` | an edge the reduction removes (G5) | warning |
/// | `taskalisk.small-container` | a container with fewer than two children | warning |
/// | `taskalisk.edge-density` | a plan whose edge density is outside its band | warning |
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
/// without a document and a valid document without warnings have none. Each
/// finding's severity is its code's: the warnings are V10, which is the one
/// warning label, and every violation's label is an error.
#[must_use]
pub fn findings(body: &str, address: &IssueRef) -> Vec<Finding> {
    match admit(body, Some(address)) {
        Judgement::NoDocument => Vec::new(),
        Judgement::Valid { warnings, .. } => from_labels(address, &warnings),
        Judgement::Invalid(validation) => from_labels(address, &validation.violations),
    }
}

/// One finding per label, under one subject, sorted by code.
fn from_labels<'a>(
    subject: &IssueRef,
    labels: impl IntoIterator<Item = &'a Label>,
) -> Vec<Finding> {
    let mut found: Vec<Finding> = labels
        .into_iter()
        .map(|&label| Finding::new(subject.clone(), Rule::Document(label), None))
        .collect();
    found.sort();
    found
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::{Finding, PROFILE_RULES, Rule, Severity, from_labels};
    use crate::LABELS;
    use crate::label::Label;
    use crate::reference::IssueRef;

    /// F5: a finding is its subject, its rule and the reference it concerns.
    /// Wording and severity are not part of its identity.
    #[test]
    fn f5_wording_and_severity_are_not_part_of_a_findings_identity() {
        use std::collections::hash_map::DefaultHasher;
        use std::hash::{Hash, Hasher};

        let subject = IssueRef::parse("o/r#1").expect("a reference");
        let concerns = IssueRef::parse("o/r#2").expect("a reference");
        let a = Finding::new(subject, Rule::D5, Some(concerns));
        let mut b = a.clone();
        b.message = "other wording";
        b.severity = Severity::Warning;
        assert_eq!(a, b);
        assert_eq!(a.cmp(&b), core::cmp::Ordering::Equal);
        let hash = |f: &Finding| {
            let mut h = DefaultHasher::new();
            f.hash(&mut h);
            h.finish()
        };
        assert_eq!(hash(&a), hash(&b));
        assert_eq!(BTreeSet::from([a.clone(), b]).len(), 1);
        // A different reference concerned is a different finding (X3).
        let mut c = a.clone();
        c.concerns = IssueRef::parse("o/r#3");
        assert_ne!(a, c);
    }

    /// Label order is not code order: `version.P3` sits between `format.L4`
    /// and `format.V1` as a label, after every `format.` code as a code.
    #[test]
    fn findings_come_out_in_code_text_order() {
        let subject = IssueRef::parse("o/r#1").expect("a reference");
        let found = from_labels(&subject, &[Label::P3, Label::V1]);
        let codes: Vec<&str> = found.iter().map(|f| f.code.as_str()).collect();
        assert_eq!(codes, ["format.V1", "version.P3"]);
    }

    /// Every rule a finding can carry, document labels and profile rules
    /// alike, has its own code; its suffix is the rule's label, and its
    /// prefix the document that states the rule.
    #[test]
    fn every_rule_has_a_distinct_code_ending_in_its_label() {
        let rules: Vec<Rule> = LABELS
            .iter()
            .map(|&l| Rule::Document(l))
            .chain(PROFILE_RULES)
            .collect();
        let codes: BTreeSet<&str> = rules.iter().map(|r| r.code()).collect();
        assert_eq!(codes.len(), rules.len());
        let subject = IssueRef::parse("o/r#1").expect("a reference");
        for rule in rules {
            let finding = Finding::new(subject.clone(), rule, None);
            assert_eq!(finding.label(), rule.as_str(), "{}", finding.code);
            let (prefix, _) = finding
                .code
                .as_str()
                .split_once('.')
                .expect("a prefixed code");
            assert!(
                ["format", "version", "profile"].contains(&prefix),
                "{}",
                finding.code
            );
            assert!(!finding.message.is_empty(), "{}", finding.code);
        }
    }

    #[test]
    fn profile_rules_are_errors_with_profile_codes() {
        let codes: Vec<&str> = PROFILE_RULES.iter().map(|r| r.code()).collect();
        assert_eq!(
            codes,
            [
                "profile.D3",
                "profile.D4",
                "profile.D5",
                "profile.X2",
                "profile.X3",
                "profile.G4"
            ]
        );
        assert!(
            PROFILE_RULES
                .iter()
                .all(|r| r.severity() == Severity::Error)
        );
        assert_eq!(Rule::Document(Label::V10).severity(), Severity::Warning);
        assert_eq!(Rule::Document(Label::X1).code(), "profile.X1");
    }
}
