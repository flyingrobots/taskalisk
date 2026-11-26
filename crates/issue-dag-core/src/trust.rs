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

use crate::admission::{Distrusted, NotAdmitted};
use crate::finding::{Code, Finding, Severity};
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

/// One issue or pull request the trust gate kept out, for one actor.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TrustFinding {
    /// The finding: its subject (the issue, or the pull request's own
    /// address), its code and a fixed message. It concerns no reference.
    pub finding: Finding,
    /// The login that failed, as recorded: the author's or the editor's, or
    /// a pull request's author; `None` for a deleted account.
    pub login: Option<String>,
    /// The rule that did not trust it: `AD2` or `AD5.<step>` for an actor
    /// (see [`crate::Distrust::rule`]), `AD9` for a pull request whose head
    /// is not a branch of the home repository.
    pub rule: &'static str,
}

const fn finding(subject: IssueRef, code: &str, message: &'static str) -> Finding {
    Finding::coded(subject, Code::of(code), None, message)
}

fn of_actor(subject: &IssueRef, code: &str, message: &'static str, d: &Distrusted) -> TrustFinding {
    TrustFinding {
        finding: finding(subject.clone(), code, message),
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
///   the issues. Its subject is the pull request's own address; its login is
///   its author's, judged or not.
///
/// Two findings can share an identity (profile rule F5) when two editors of
/// one issue fail: the list keeps both, each with its own login.
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
        // A pull request's number is an issue number of its repository;
        // GitHub's numbers are far below the bound of format rule L1.
        let Some(subject) = IssueRef::parse(&format!("{}#{}", pull.repository, pull.number)) else {
            continue;
        };
        found.push(TrustFinding {
            finding: finding(
                subject,
                UNTRUSTED_PULL_REQUEST,
                "the pull request closes an issue and is not admitted (admission rule AD9): it \
                 has no effect on the status of what it closes",
            ),
            login: pull.author.clone(),
            rule: pull.reason.rule(),
        });
    }
    found
}
