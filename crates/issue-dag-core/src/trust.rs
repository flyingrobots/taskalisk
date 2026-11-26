//! Trust findings (flyingrobots/taskalisk#46).
//!
//! Each issue and pull request that the trust gate kept out of a run's graph,
//! with the reason the admission policy gave (`taskalisk/threat-model`, rules
//! AD1 to AD10): an untrusted author (AD8 step 1), an untrusted editor of the
//! body (AD8 step 3), or a pull request that closes an issue and is not
//! admitted (AD9). The planning profile gives the admission rules no finding
//! of their own, so these are Taskalisk's: their codes carry the prefix
//! `taskalisk.`, each is a warning, and none makes a run invalid.
//! [`trust_findings`] reads them from a run's [`Discovered`], which an
//! invalid run reports too (decision D13).
//!
//! A finding carries its subject, the login that failed and the rule that
//! did not trust it, and a fixed message. Never a title or a line of a body
//! (threat model C1, C3): the admission policy reads neither to decide.

use core::fmt;

use crate::admission::{Distrusted, NotAdmitted};
use crate::finding::{Code, Severity};
use crate::observation::Repo;
use crate::plan::Discovered;
use crate::reference::IssueRef;

/// The code of an issue whose author is not trusted.
const UNTRUSTED_AUTHOR: &str = "taskalisk.untrusted-author";
/// The code of an issue an untrusted editor edited.
const UNTRUSTED_EDITOR: &str = "taskalisk.untrusted-editor";
/// The code of a pull request that is not admitted.
const UNTRUSTED_PULL_REQUEST: &str = "taskalisk.untrusted-pull-request";

/// Every trust warning's code, once each, in the order of its text.
pub const TRUST_WARNINGS: [&str; 3] = [UNTRUSTED_AUTHOR, UNTRUSTED_EDITOR, UNTRUSTED_PULL_REQUEST];

/// The codes of [`TRUST_WARNINGS`] with their severity, in its order: this
/// family's entry in [`crate::CODES`].
pub const TRUST_CODES: [(&str, Severity); TRUST_WARNINGS.len()] = [
    (UNTRUSTED_AUTHOR, Severity::Warning),
    (UNTRUSTED_EDITOR, Severity::Warning),
    (UNTRUSTED_PULL_REQUEST, Severity::Warning),
];

/// What a trust finding is about: an issue, or a pull request of the home
/// repository. A pull request's number is any number GitHub gives, so it is
/// held as observed, never parsed into a reference (rule L1 bounds those).
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TrustSubject {
    /// An issue the trust gate did not admit.
    Issue(IssueRef),
    /// A pull request that closes an issue and is not admitted.
    PullRequest {
        /// Its repository, the home repository.
        repository: Repo,
        /// Its number, as observed.
        number: u64,
    },
}

impl fmt::Display for TrustSubject {
    /// `owner/repo#N`, for an issue and a pull request alike.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Issue(id) => write!(f, "{id}"),
            Self::PullRequest { repository, number } => write!(f, "{repository}#{number}"),
        }
    }
}

/// One issue or pull request the trust gate kept out, for one actor: a
/// catalogued code, its severity, a fixed message, the subject, the login
/// and the rule. It is not a [`crate::Finding`], whose subject is always a
/// reference: a pull request's number need not fit one, and its finding is
/// never dropped for that.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TrustFinding {
    /// The issue or pull request it is about.
    pub subject: TrustSubject,
    /// The stable code, an entry of [`crate::CODES`]; read with
    /// [`TrustFinding::code`].
    code: Code,
    /// Fixed text for the code. It never carries a login, a title or a line
    /// of a body.
    pub message: &'static str,
    /// The login that failed, as recorded: the author's or the editor's, or
    /// a pull request's author; `None` for a deleted account.
    pub login: Option<String>,
    /// The rule that did not trust it: `AD2` or `AD5.<step>` for an actor
    /// (see [`crate::Distrust::rule`]), `AD9` for a pull request whose head
    /// is not a branch of the home repository.
    pub rule: &'static str,
}

impl TrustFinding {
    /// The stable code, an entry of [`crate::CODES`].
    #[must_use]
    pub const fn code(&self) -> Code {
        self.code
    }

    /// The severity of its code, [`Code::severity`]: a warning.
    #[must_use]
    pub const fn severity(&self) -> Severity {
        self.code.severity()
    }
}

fn of_actor(subject: &IssueRef, code: &str, message: &'static str, d: &Distrusted) -> TrustFinding {
    TrustFinding {
        subject: TrustSubject::Issue(subject.clone()),
        code: Code::of(code),
        message,
        login: d.login.clone(),
        rule: d.why.rule(),
    }
}

/// The trust findings of a run, from what its discovery read.
///
/// - `taskalisk.untrusted-author`, once for each issue whose author is not
///   trusted (AD8 step 1), in the order of the issues' references.
/// - `taskalisk.untrusted-editor`, once for each distinct editor of an
///   issue's body who is not trusted (AD8 step 3), in the order of the edit
///   history, the issues in the order of their references.
/// - `taskalisk.untrusted-pull-request`, once for each pull request that
///   closes an issue and is not admitted (AD9), in the order observed, after
///   the issues. Its subject is the pull request itself; its login is
///   its author's, judged or not.
///
/// Two editors of one issue that fail give two findings, each with its own
/// login. Nothing is left out: every untrusted issue and pull request in
/// `discovered` gives at least one.
#[must_use]
pub fn trust_findings(discovered: &Discovered) -> Vec<TrustFinding> {
    let mut found = Vec::new();
    for (id, issue) in &discovered.untrusted_issue_reasons {
        match &issue.reason {
            NotAdmitted::Author(d) => found.push(of_actor(
                id,
                UNTRUSTED_AUTHOR,
                "the issue's author is not trusted (admission rule AD8, step 1): the issue is no \
                 node, and only an opaque blocker of a trusted issue that names it",
                d,
            )),
            NotAdmitted::Editors(editors) => {
                for d in editors {
                    found.push(of_actor(
                        id,
                        UNTRUSTED_EDITOR,
                        "an editor of the issue's body is not trusted (admission rule AD8, step \
                         3): the issue is no node, and only an opaque blocker of a trusted issue \
                         that names it",
                        d,
                    ));
                }
            }
        }
    }
    for pull in &discovered.untrusted_pull_request_reasons {
        found.push(TrustFinding {
            subject: TrustSubject::PullRequest {
                repository: pull.repository.clone(),
                number: pull.number,
            },
            code: Code::of(UNTRUSTED_PULL_REQUEST),
            message: "the pull request closes an issue and is not admitted (admission rule AD9): \
                      it has no effect on the status of what it closes",
            login: pull.author.clone(),
            rule: pull.reason.rule(),
        });
    }
    found
}
