//! The edge edit (flyingrobots/taskalisk#1): the forge write port, the checks
//! an edit passes before any write, and the final reread (edge-edit
//! contract, rules E1 to E10).
//!
//! The write replaces the whole issue body (decision 0001, section 2): a
//! narrow logical edit does not narrow its effect. GitHub documents no
//! conditional update of an issue, so the reread before the write is an
//! optimistic check, not a lock (E8): an edit made between the reread and
//! the write can be lost, and a change to another issue after the checks
//! can make the graph invalid; the next plan reports it. Nothing restores
//! a body after a write, and a failed write is never retried (E9).

use std::cell::RefCell;
use std::collections::BTreeMap;

use crate::admission::Undecided;
use crate::finding::Finding;
use crate::forge::Forge;
use crate::observation::{
    Actor, Body, CodeownersFile, Issue, Lookup, Missing, NotFound, Observed,
    Parameters, PullRequest, Repo,
};
use crate::plan::Rejection;
use crate::reference::IssueRef;
use crate::rewrite::{EdgeEdit, Refusal, Rewrite};

/// The forge write port: the one write an edge edit makes, and the account
/// it is made as.
pub trait ForgeWrite {
    /// Why a write failed. A failed write may still have been applied: the
    /// caller reports it and never retries or restores (E9).
    type Error;

    /// The account a write is made as (E7). Unavailable when it cannot be
    /// identified, such as for a token that cannot read its own account.
    fn writer(&self) -> Observed<Actor>;

    /// Replaces the whole body of `issue` with `body`, in one request.
    ///
    /// # Errors
    ///
    /// [`ForgeWrite::Error`] when the request failed or its answer was
    /// lost; whether the body changed is then unknown.
    fn replace_body(&self, issue: &IssueRef, body: &str) -> Result<(), Self::Error>;
}

/// What the final reread observed changed since the checks (E7).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Conflict {
    /// The child no longer resolves to the issue it was: it is unavailable
    /// at its address, a pull request, or transferred.
    Address,
    /// Its body differs from the body the checks validated.
    Body,
    /// Its author or an editor of its body is no longer admitted.
    Trust,
}

/// Why an edge edit is refused. In every case nothing was written (E10).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EditRefusal {
    /// A reference the edit needs in the read scope is outside it (E2).
    OutOfScope(IssueRef),
    /// The child is a pull request (E3).
    PullRequest,
    /// The child was transferred to this address (E3).
    Transferred(IssueRef),
    /// The child, its author or an editor of its body, is not admitted
    /// (E3).
    Untrusted,
    /// The child's body cannot take the edit (E1, E3, E3a, E4).
    Document(Refusal),
    /// The edit closes a cycle (E6, E6a): the nodes of the plan with the
    /// edit that a cycle newly reaches.
    Cycle(Vec<IssueRef>),
    /// The plan with the edit has violations, references outside the
    /// scope or unknown prerequisites that the plan without it lacks (E6a).
    NewFindings(Vec<Finding>),
    /// The final reread observed a change (E7).
    Conflict(Conflict),
    /// An observation the checks need is unavailable (E10): the outcome is
    /// incomplete.
    Incomplete {
        /// Why, as the forge recorded it.
        unavailable: String,
        /// Which part of a reference was not found, when recorded.
        cause: Option<NotFound>,
    },
    /// An observation was not recorded (bundle rule OB5).
    Missing(Missing),
    /// A run parameter is invalid (profile rule I2).
    Rejected(Rejection),
}

impl From<Undecided> for EditRefusal {
    fn from(undecided: Undecided) -> Self {
        match undecided {
            Undecided::Unavailable(unavailable) => Self::Incomplete {
                unavailable,
                cause: None,
            },
            Undecided::NotFound(unavailable, cause) => Self::Incomplete {
                unavailable,
                cause: Some(cause),
            },
            Undecided::Missing(missing) => Self::Missing(missing),
        }
    }
}

impl From<Missing> for EditRefusal {
    fn from(missing: Missing) -> Self {
        Self::Missing(missing)
    }
}

/// An edit that passed the checks before the write (E1 to E6).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Checked {
    /// The child.
    pub child: IssueRef,
    /// The child's body as the checks read and validated it.
    pub body: Body,
    /// The new body; when it is unchanged nothing is written (E5).
    pub rewrite: Rewrite,
}

/// A forge that answers the child's body with a proposed text, and
/// otherwise as the forge it wraps: the closure with the edit applied in
/// memory (E6). Every body it answers is kept, for the cycle check.
pub struct Proposed<'a, F: Forge + ?Sized> {
    inner: &'a F,
    child: IssueRef,
    body: Option<String>,
    seed: bool,
    served: RefCell<BTreeMap<IssueRef, Body>>,
}

impl<'a, F: Forge + ?Sized> Proposed<'a, F> {
    /// The forge `inner` with the child's body replaced by `body`, or
    /// unchanged when `body` is `None`.
    #[must_use]
    pub fn new(inner: &'a F, child: &IssueRef, body: Option<String>) -> Self {
        Self {
            inner,
            child: child.clone(),
            body,
            seed: false,
            served: RefCell::new(BTreeMap::new()),
        }
    }

    /// Lists the child among the open home issues, so a run without roots
    /// reaches it even when the listing does not (E6).
    #[must_use]
    pub const fn seeding(mut self) -> Self {
        self.seed = true;
        self
    }

    /// Every body answered so far, by reference.
    fn served(&self) -> BTreeMap<IssueRef, Body> {
        self.served.borrow().clone()
    }
}

impl<F: Forge + ?Sized> Forge for Proposed<'_, F> {
    fn home_open_issues(&self) -> Lookup<Vec<IssueRef>> {
        let _ = self.seed;
        unimplemented!("flyingrobots/taskalisk#1")
    }

    fn home_open_pull_requests(&self) -> Lookup<Vec<PullRequest>> {
        self.inner.home_open_pull_requests()
    }

    fn issue(&self, reference: &IssueRef) -> Lookup<Issue> {
        self.inner.issue(reference)
    }

    fn not_found(&self, reference: &IssueRef) -> Option<NotFound> {
        let _ = reference;
        unimplemented!("flyingrobots/taskalisk#1")
    }

    fn body(&self, reference: &IssueRef) -> Lookup<Body> {
        let _ = (&self.body, &self.child, self.served());
        let _ = reference;
        unimplemented!("flyingrobots/taskalisk#1")
    }

    fn permission(&self, repo: &Repo, login: &str) -> Lookup<Option<String>> {
        self.inner.permission(repo, login)
    }

    fn codeowners(&self, repo: &Repo) -> Lookup<Option<CodeownersFile>> {
        self.inner.codeowners(repo)
    }
}

/// Checks an edge edit of `child` before any write (E1 to E6): the scope,
/// the child's issue, its admission and its body, the rewrite, and, when
/// the body changes, the plan with the edit against the plan without it,
/// with the child among the seeds even when the roots do not reach it.
///
/// # Errors
///
/// An [`EditRefusal`]: nothing is to be written.
pub fn check_edit<F: Forge + ?Sized>(
    parameters: &Parameters,
    forge: &F,
    child: &IssueRef,
    edit: &EdgeEdit,
) -> Result<Checked, EditRefusal> {
    let _ = (parameters, forge, child, edit);
    unimplemented!("flyingrobots/taskalisk#1")
}

/// Whether the account a write is made as is admitted in the child's
/// repository under the run's trust policy (E7). An account with no login
/// is not.
///
/// # Errors
///
/// [`Undecided`] when a lookup the policy reaches cannot be made.
pub fn writer_admitted<F: Forge + ?Sized>(
    parameters: &Parameters,
    forge: &F,
    child: &IssueRef,
    writer: &Actor,
) -> Result<bool, Undecided> {
    let _ = (parameters, forge, child, writer);
    unimplemented!("flyingrobots/taskalisk#1")
}

/// The final reread (E7): reads the child again through `fresh`, a forge
/// that has not read it yet, and refuses when its address, its body, or
/// the admission of its author and editors differs from what
/// [`check_edit`] validated.
///
/// # Errors
///
/// [`EditRefusal::Conflict`] for an observed change, or why the reread
/// could not be made.
pub fn recheck<F: Forge + ?Sized>(
    parameters: &Parameters,
    fresh: &F,
    checked: &Checked,
) -> Result<(), EditRefusal> {
    let _ = (parameters, fresh, checked);
    unimplemented!("flyingrobots/taskalisk#1")
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::{Checked, Conflict, EditRefusal, Proposed, check_edit, recheck, writer_admitted};
    use crate::finding::Rule;
    use crate::forge::{Forge, Observations, RecordedForge};
    use crate::observation::{
        Actor, Body, Issue, IssueState, NotFound, Observed, Parameters, ReadScope, Repo,
        TRUST_POLICY, TrustParameters,
    };
    use crate::reference::IssueRef;
    use crate::rewrite::{EdgeEdit, Refusal};

    fn r(text: &str) -> IssueRef {
        IssueRef::parse(text).expect("a reference")
    }

    fn actor(login: &str) -> Actor {
        Actor {
            login: login.to_owned(),
            actor_type: "User".to_owned(),
        }
    }

    fn task(id: &str, blocked_by: &[&str]) -> String {
        format!(
            "```yaml\n.dag: issue-dag/2\n.id: {id}\n.kind: task\n.type: feature\n.blocked_by: [{}]\n```\n\n## Outcome\n\nText.\n",
            blocked_by.join(", ")
        )
    }

    /// A backlog of `o/r`: each issue open, by the owner, with its body.
    fn backlog(issues: &[(&str, String)]) -> Observations {
        let mut observations = Observations {
            home_open_issues: Some(Observed::Value(
                issues
                    .iter()
                    .map(|(id, _)| r(id))
                    .filter(|id| id.owner() == "o" && id.repo() == "r")
                    .collect(),
            )),
            home_open_pull_requests: Some(Observed::Value(Vec::new())),
            ..Observations::default()
        };
        for (id, body) in issues {
            put(&mut observations, id, body, &["owner"]);
        }
        observations
    }

    fn put(observations: &mut Observations, id: &str, body: &str, editors: &[&str]) {
        let reference = r(id);
        observations.issues.insert(
            reference.clone(),
            Observed::Value(Issue {
                address: reference.clone(),
                pull_request: false,
                state: IssueState::Open,
                state_reason: None,
                author: Some(actor("owner")),
                author_association: Some("OWNER".to_owned()),
            }),
        );
        observations.bodies.insert(
            reference,
            Observed::Value(Body {
                text: body.to_owned(),
                editors: editors.iter().map(|e| Some(actor(e))).collect(),
            }),
        );
    }

    fn parameters(roots: &[&str]) -> Parameters {
        Parameters {
            home: Repo::parse("o/r").expect("a repository"),
            roots: roots.iter().map(|&s| s.to_owned()).collect(),
            read_scope: ReadScope {
                owners: ["o".to_owned()].into(),
                repositories: [].into(),
            },
            trust: TrustParameters {
                policy: TRUST_POLICY.to_owned(),
                logins: Vec::new(),
                codeowners: false,
            },
            capacities: BTreeMap::new(),
        }
    }

    fn add(parent: &str) -> EdgeEdit {
        EdgeEdit::Add(r(parent))
    }

    fn remove(parent: &str) -> EdgeEdit {
        EdgeEdit::Remove(r(parent))
    }

    /// 1 <- 2 <- 3 (2 waits on 1, 3 on 2), and 5 alone.
    fn chain() -> Observations {
        backlog(&[
            ("o/r#1", task("o/r#1", &[])),
            ("o/r#2", task("o/r#2", &["o/r#1"])),
            ("o/r#3", task("o/r#3", &["o/r#2"])),
            ("o/r#5", task("o/r#5", &[])),
        ])
    }

    fn check(
        observations: &Observations,
        roots: &[&str],
        child: &str,
        edit: &EdgeEdit,
    ) -> Result<Checked, EditRefusal> {
        check_edit(
            &parameters(roots),
            &RecordedForge::new(observations),
            &r(child),
            edit,
        )
    }

    #[test]
    fn an_edit_that_closes_a_cycle_is_refused() {
        let refused = check(&chain(), &[], "o/r#1", &add("o/r#3"));
        assert!(
            matches!(&refused, Err(EditRefusal::Cycle(nodes)) if nodes.contains(&r("o/r#1"))),
            "{refused:?}"
        );
    }

    #[test]
    fn a_cycle_is_refused_when_the_roots_do_not_reach_the_child() {
        let refused = check(&chain(), &["o/r#5"], "o/r#1", &add("o/r#3"));
        assert!(matches!(refused, Err(EditRefusal::Cycle(_))), "{refused:?}");
    }

    #[test]
    fn a_cycle_downstream_of_an_existing_cycle_is_still_refused() {
        // 8 and 9 wait on each other; 1 waits on 8, 2 on 1. Every one of
        // them is already a G4 node, so only reachability (E6a) shows that
        // 2 -> 1 closes a new cycle.
        let observations = backlog(&[
            ("o/r#8", task("o/r#8", &["o/r#9"])),
            ("o/r#9", task("o/r#9", &["o/r#8"])),
            ("o/r#1", task("o/r#1", &["o/r#8"])),
            ("o/r#2", task("o/r#2", &["o/r#1"])),
        ]);
        let refused = check(&observations, &[], "o/r#1", &add("o/r#2"));
        assert!(matches!(refused, Err(EditRefusal::Cycle(_))), "{refused:?}");
    }

    #[test]
    fn an_edit_that_leaves_an_existing_problem_unchanged_passes() {
        // 6 names a repository outside the scope (D3) before and after.
        let mut observations = chain();
        put(&mut observations, "o/r#6", &task("o/r#6", &["x/y#1"]), &["owner"]);
        if let Some(Observed::Value(listing)) = &mut observations.home_open_issues {
            listing.push(r("o/r#6"));
        }
        let checked = check(&observations, &[], "o/r#5", &add("o/r#1")).expect("passes");
        assert!(checked.rewrite.changed);
        assert!(checked.rewrite.body.contains(".blocked_by: [o/r#1]"));
    }

    #[test]
    fn a_violation_the_edit_brings_into_the_plan_is_refused() {
        // 7 is invalid and outside the plan until 5 names it.
        let mut observations = chain();
        put(&mut observations, "o/r#7", "```yaml\n.dag: issue-dag/2\n.id: o/r#7\n.kind: task\n```\n", &["owner"]);
        let refused = check(&observations, &["o/r#5"], "o/r#5", &add("o/r#7"));
        match refused {
            Err(EditRefusal::NewFindings(findings)) => {
                assert!(findings.iter().all(|f| f.subject == r("o/r#7")), "{findings:?}");
            }
            other => panic!("expected new findings, got {other:?}"),
        }
    }

    #[test]
    fn an_unknown_prerequisite_the_edit_adds_is_refused() {
        // 4 is a pull request: neither a node nor a container (X3).
        let mut observations = chain();
        put(&mut observations, "o/r#4", "", &["owner"]);
        if let Some(Observed::Value(issue)) = observations.issues.get_mut(&r("o/r#4")) {
            issue.pull_request = true;
        }
        let refused = check(&observations, &[], "o/r#5", &add("o/r#4"));
        assert!(
            matches!(&refused, Err(EditRefusal::NewFindings(f)) if f.iter().any(|f| f.code() == Rule::X3.code())),
            "{refused:?}"
        );
    }

    #[test]
    fn a_lookup_the_plan_with_the_edit_needs_makes_the_edit_incomplete() {
        let mut observations = chain();
        observations
            .issues
            .insert(r("o/r#40"), Observed::Unavailable("HTTP 502".to_owned()));
        let refused = check(&observations, &[], "o/r#5", &add("o/r#40"));
        assert_eq!(
            refused,
            Err(EditRefusal::Incomplete {
                unavailable: "HTTP 502".to_owned(),
                cause: None
            })
        );
    }

    #[test]
    fn a_child_that_cannot_be_read_is_incomplete_with_its_cause() {
        let mut observations = chain();
        observations
            .issues
            .insert(r("o/r#41"), Observed::Unavailable("404".to_owned()));
        observations.not_found.insert(r("o/r#41"), NotFound::Number);
        let refused = check(&observations, &[], "o/r#41", &add("o/r#1"));
        assert_eq!(
            refused,
            Err(EditRefusal::Incomplete {
                unavailable: "404".to_owned(),
                cause: Some(NotFound::Number)
            })
        );
    }

    #[test]
    fn scope_is_checked_for_the_child_and_for_an_added_parent_only() {
        let observations = chain();
        assert_eq!(
            check(&observations, &[], "x/y#1", &add("o/r#1")),
            Err(EditRefusal::OutOfScope(r("x/y#1")))
        );
        assert_eq!(
            check(&observations, &[], "o/r#5", &add("x/y#1")),
            Err(EditRefusal::OutOfScope(r("x/y#1")))
        );
    }

    #[test]
    fn remove_repairs_a_reference_outside_the_scope() {
        let mut observations = chain();
        put(&mut observations, "o/r#5", &task("o/r#5", &["x/y#1", "o/r#1"]), &["owner"]);
        let checked = check(&observations, &[], "o/r#5", &remove("x/y#1")).expect("passes");
        assert!(checked.rewrite.body.contains(".blocked_by: [o/r#1]"));
    }

    #[test]
    fn a_no_op_passes_unchanged() {
        let checked = check(&chain(), &[], "o/r#2", &add("o/r#1")).expect("passes");
        assert!(!checked.rewrite.changed);
    }

    #[test]
    fn the_child_must_be_an_admitted_issue_with_a_task_document() {
        let mut observations = chain();
        put(&mut observations, "o/r#5", &task("o/r#5", &[]), &["owner", "mallory"]);
        observations
            .permissions
            .entry(Repo::parse("o/r").expect("a repository"))
            .or_default()
            .insert("mallory".to_owned(), Observed::Value(None));
        assert_eq!(
            check(&observations, &[], "o/r#5", &add("o/r#1")),
            Err(EditRefusal::Untrusted)
        );
        let mut observations = chain();
        put(&mut observations, "o/r#5", "No frontmatter.\n", &["owner"]);
        assert_eq!(
            check(&observations, &[], "o/r#5", &add("o/r#1")),
            Err(EditRefusal::Document(Refusal::NoDocument))
        );
        let mut observations = chain();
        if let Some(Observed::Value(issue)) = observations.issues.get_mut(&r("o/r#5")) {
            issue.pull_request = true;
        }
        assert_eq!(
            check(&observations, &[], "o/r#5", &add("o/r#1")),
            Err(EditRefusal::PullRequest)
        );
        let mut observations = chain();
        if let Some(Observed::Value(issue)) = observations.issues.get_mut(&r("o/r#5")) {
            issue.address = r("o/s#5");
        }
        assert_eq!(
            check(&observations, &[], "o/r#5", &add("o/r#1")),
            Err(EditRefusal::Transferred(r("o/s#5")))
        );
    }

    fn checked_five() -> (Observations, Checked) {
        let observations = chain();
        let checked = check(&observations, &[], "o/r#5", &add("o/r#1")).expect("passes");
        (observations, checked)
    }

    #[test]
    fn the_final_reread_passes_an_unchanged_child() {
        let (observations, checked) = checked_five();
        assert_eq!(
            recheck(&parameters(&[]), &RecordedForge::new(&observations), &checked),
            Ok(())
        );
    }

    #[test]
    fn the_final_reread_refuses_a_changed_body() {
        let (mut observations, checked) = checked_five();
        put(&mut observations, "o/r#5", &task("o/r#5", &["o/r#2"]), &["owner"]);
        assert_eq!(
            recheck(&parameters(&[]), &RecordedForge::new(&observations), &checked),
            Err(EditRefusal::Conflict(Conflict::Body))
        );
    }

    #[test]
    fn the_final_reread_refuses_a_newly_untrusted_editor() {
        let (mut observations, checked) = checked_five();
        put(&mut observations, "o/r#5", &checked.body.text, &["owner", "mallory"]);
        observations
            .permissions
            .entry(Repo::parse("o/r").expect("a repository"))
            .or_default()
            .insert("mallory".to_owned(), Observed::Value(Some("read".to_owned())));
        assert_eq!(
            recheck(&parameters(&[]), &RecordedForge::new(&observations), &checked),
            Err(EditRefusal::Conflict(Conflict::Trust))
        );
    }

    #[test]
    fn the_final_reread_refuses_a_moved_child_and_reports_a_failed_read() {
        let (mut observations, checked) = checked_five();
        if let Some(Observed::Value(issue)) = observations.issues.get_mut(&r("o/r#5")) {
            issue.address = r("o/s#5");
        }
        assert_eq!(
            recheck(&parameters(&[]), &RecordedForge::new(&observations), &checked),
            Err(EditRefusal::Conflict(Conflict::Address))
        );
        observations
            .bodies
            .insert(r("o/r#5"), Observed::Unavailable("HTTP 502".to_owned()));
        if let Some(Observed::Value(issue)) = observations.issues.get_mut(&r("o/r#5")) {
            issue.address = r("o/r#5");
        }
        assert_eq!(
            recheck(&parameters(&[]), &RecordedForge::new(&observations), &checked),
            Err(EditRefusal::Incomplete {
                unavailable: "HTTP 502".to_owned(),
                cause: None
            })
        );
    }

    #[test]
    fn the_writer_is_judged_under_the_same_policy() {
        let mut observations = chain();
        let repo = Repo::parse("o/r").expect("a repository");
        let table = observations.permissions.entry(repo).or_default();
        table.insert("dev".to_owned(), Observed::Value(Some("write".to_owned())));
        table.insert("mallory".to_owned(), Observed::Value(None));
        let forge = RecordedForge::new(&observations);
        let child = r("o/r#5");
        let mut with_bot = parameters(&[]);
        with_bot.trust.logins = vec!["helper[bot]".to_owned()];
        let bot = Actor {
            login: "helper".to_owned(),
            actor_type: "Bot".to_owned(),
        };
        assert_eq!(writer_admitted(&parameters(&[]), &forge, &child, &actor("dev")), Ok(true));
        assert_eq!(writer_admitted(&parameters(&[]), &forge, &child, &actor("mallory")), Ok(false));
        assert_eq!(writer_admitted(&parameters(&[]), &forge, &child, &actor("")), Ok(false));
        assert_eq!(writer_admitted(&parameters(&[]), &forge, &child, &bot), Ok(false));
        assert_eq!(writer_admitted(&with_bot, &forge, &child, &bot), Ok(true));
        assert!(writer_admitted(&parameters(&[]), &forge, &child, &actor("nobody")).is_err());
    }

    #[test]
    fn the_proposed_forge_answers_the_childs_body_and_lists_it() {
        let mut observations = chain();
        observations
            .issues
            .insert(r("o/r#41"), Observed::Unavailable("404".to_owned()));
        observations.not_found.insert(r("o/r#41"), NotFound::Owner);
        put(&mut observations, "o/s#2", &task("o/s#2", &[]), &["owner"]);
        let forge = RecordedForge::new(&observations);
        let proposed = Proposed::new(&forge, &r("o/s#2"), Some("new".to_owned())).seeding();
        assert_eq!(
            proposed.body(&r("o/s#2")).map(|b| match b {
                Observed::Value(body) => body.text,
                Observed::Unavailable(why) => why,
            }),
            Ok("new".to_owned())
        );
        assert!(matches!(
            proposed.home_open_issues(),
            Ok(Observed::Value(listing)) if listing.contains(&r("o/s#2"))
        ));
        assert_eq!(proposed.not_found(&r("o/r#41")), Some(NotFound::Owner));
        let unchanged = Proposed::new(&forge, &r("o/s#2"), None);
        assert_eq!(unchanged.body(&r("o/r#1")), forge.body(&r("o/r#1")));
        assert!(matches!(
            unchanged.home_open_issues(),
            Ok(Observed::Value(listing)) if !listing.contains(&r("o/s#2"))
        ));
    }
}
