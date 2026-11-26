//! The ports the planner reads through, and an in-memory forge that answers
//! from recorded observations (decision 0001, section 2).

use std::collections::BTreeMap;

use crate::observation::{
    Body, CodeownersFile, Issue, Lookup, Missing, Observed, Parameters, PullRequest, Repo,
};
use crate::reference::IssueRef;

/// The forge, the port every observation of a run is read through.
///
/// Each observation of the profile and the admission policy is one lookup
/// here. Each answer is a slot ([`Observed`]): an unavailable one
/// makes the run incomplete, never empty. [`Missing`] means the observation
/// was not recorded at all, which makes the evidence unusable (bundle rule
/// OB5).
pub trait Forge {
    /// The references of every open issue of the home repository that is
    /// not a pull request (profile rule I4, bundle rule OB6).
    ///
    /// # Errors
    ///
    /// [`Missing`] when the listing was not recorded.
    fn home_open_issues(&self) -> Lookup<Vec<IssueRef>>;

    /// The open pull requests of the home repository (bundle rule OB7).
    ///
    /// # Errors
    ///
    /// [`Missing`] when the list was not recorded.
    fn home_open_pull_requests(&self) -> Lookup<Vec<PullRequest>>;

    /// What a reference resolves to (bundle rule OB8). Unavailable when it
    /// resolves to nothing the planner can see (profile rule D10).
    ///
    /// # Errors
    ///
    /// [`Missing`] when the issue was not recorded.
    fn issue(&self, reference: &IssueRef) -> Lookup<Issue>;

    /// The body of the issue a reference resolves to, and the actor of
    /// every edit of it (bundle rule OB8). A separate read from
    /// [`Forge::issue`], so that a planner reads it only for an issue whose
    /// author is trusted: an issue a stranger wrote costs no further query
    /// (threat model C15).
    ///
    /// # Errors
    ///
    /// [`Missing`] when the body was not recorded.
    fn body(&self, reference: &IssueRef) -> Lookup<Body>;

    /// The permission of a login on a repository (bundle rule OB10), or
    /// `None` when the login is not a collaborator. `login` is in lower case.
    ///
    /// # Errors
    ///
    /// [`Missing`] when the permission was not recorded.
    fn permission(&self, repo: &Repo, login: &str) -> Lookup<Option<String>>;

    /// The CODEOWNERS file of a repository, or `None` when it has none
    /// (bundle rule OB11).
    ///
    /// # Errors
    ///
    /// [`Missing`] when the file was not recorded.
    fn codeowners(&self, repo: &Repo) -> Lookup<Option<CodeownersFile>>;
}

/// The local repository, the port local state is read through.
///
/// The `issue-dag-planning/2` profile reads nothing from it: branch names
/// are hints outside the profile (its section 13). The port exists so that
/// adapters and later profiles have one place to read local state from.
pub trait LocalRepository {
    /// The names of the local branches.
    fn branch_names(&self) -> Observed<Vec<String>>;
}

/// A local repository with no branches, for runs that read none.
#[derive(Clone, Copy, Debug, Default)]
pub struct NoLocalRepository;

impl LocalRepository for NoLocalRepository {
    fn branch_names(&self) -> Observed<Vec<String>> {
        Observed::Value(Vec::new())
    }
}

/// The observations of one run, as recorded (bundle section 2). A member
/// that is `None`, or a key a map lacks, was not recorded.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Observations {
    /// `home_open_issues` (OB6).
    pub home_open_issues: Option<Observed<Vec<IssueRef>>>,
    /// `home_open_pull_requests` (OB7).
    pub home_open_pull_requests: Option<Observed<Vec<PullRequest>>>,
    /// `issues`, keyed by the reference read (OB8).
    pub issues: BTreeMap<IssueRef, Observed<Issue>>,
    /// `permissions`: repository, then login in lower case (OB10).
    pub permissions: BTreeMap<Repo, BTreeMap<String, Observed<Option<String>>>>,
    /// `codeowners` (OB11).
    pub codeowners: Option<BTreeMap<Repo, Observed<Option<CodeownersFile>>>>,
}

/// An observation bundle (bundle rule OB1): the run parameters and the
/// observations, everything a run reads.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Bundle {
    /// The run parameters.
    pub parameters: Parameters,
    /// The observations.
    pub observations: Observations,
}

/// A forge that answers every lookup from recorded observations.
#[derive(Clone, Copy, Debug)]
pub struct RecordedForge<'a> {
    observations: &'a Observations,
}

impl<'a> RecordedForge<'a> {
    /// A forge over recorded observations.
    #[must_use]
    pub const fn new(observations: &'a Observations) -> Self {
        Self { observations }
    }
}

fn recorded<T: Clone>(slot: Option<&Observed<T>>, what: impl FnOnce() -> String) -> Lookup<T> {
    slot.cloned().ok_or_else(|| Missing { what: what() })
}

impl Forge for RecordedForge<'_> {
    fn home_open_issues(&self) -> Lookup<Vec<IssueRef>> {
        recorded(self.observations.home_open_issues.as_ref(), || {
            "the listing of the open home issues".to_owned()
        })
    }

    fn home_open_pull_requests(&self) -> Lookup<Vec<PullRequest>> {
        recorded(self.observations.home_open_pull_requests.as_ref(), || {
            "the open home pull requests".to_owned()
        })
    }

    fn issue(&self, reference: &IssueRef) -> Lookup<Issue> {
        recorded(self.observations.issues.get(reference), || {
            format!("the issue {reference}")
        })
    }

    fn body(&self, reference: &IssueRef) -> Lookup<Body> {
        let missing = || Missing {
            what: format!("the body of {reference}"),
        };
        match self.observations.issues.get(reference) {
            Some(Observed::Value(issue)) => issue.body.clone().ok_or_else(missing),
            Some(Observed::Unavailable(why)) => Ok(Observed::Unavailable(why.clone())),
            None => Err(missing()),
        }
    }

    fn permission(&self, repo: &Repo, login: &str) -> Lookup<Option<String>> {
        recorded(
            self.observations
                .permissions
                .get(repo)
                .and_then(|table| table.get(login)),
            || format!("the permission of {login} on {repo}"),
        )
    }

    fn codeowners(&self, repo: &Repo) -> Lookup<Option<CodeownersFile>> {
        recorded(
            self.observations
                .codeowners
                .as_ref()
                .and_then(|files| files.get(repo)),
            || format!("the CODEOWNERS of {repo}"),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::{Forge, Observations, RecordedForge};
    use crate::observation::{Body, Issue, IssueState, Observed, Repo};
    use crate::reference::IssueRef;

    #[test]
    fn a_slot_not_recorded_is_missing_never_empty() {
        let observations = Observations::default();
        let forge = RecordedForge::new(&observations);
        let repo = Repo::parse("o/r").expect("a repository");
        let reference = IssueRef::parse("o/r#1").expect("a reference");
        assert!(forge.home_open_issues().is_err());
        assert!(forge.home_open_pull_requests().is_err());
        assert!(forge.issue(&reference).is_err());
        assert!(forge.permission(&repo, "dev").is_err());
        assert!(forge.codeowners(&repo).is_err());
    }

    fn issue(body: Option<Observed<Body>>) -> Observed<Issue> {
        Observed::Value(Issue {
            address: IssueRef::parse("o/r#1").expect("a reference"),
            pull_request: false,
            state: IssueState::Open,
            state_reason: None,
            author: None,
            author_association: None,
            body,
        })
    }

    #[test]
    fn the_body_is_its_own_read_and_never_rides_on_the_issue() {
        let reference = IssueRef::parse("o/r#1").expect("a reference");
        let body = Observed::Value(Body {
            text: "text".to_owned(),
            editors: vec![None],
        });
        let mut observations = Observations::default();
        observations
            .issues
            .insert(reference.clone(), issue(Some(body.clone())));
        let forge = RecordedForge::new(&observations);
        assert_eq!(forge.body(&reference), Ok(body));
        // The issue is answered without its body (threat model C15).
        assert_eq!(forge.issue(&reference), Ok(issue(None)));
    }

    #[test]
    fn a_body_not_recorded_is_missing_never_empty() {
        let reference = IssueRef::parse("o/r#1").expect("a reference");
        let mut observations = Observations::default();
        let forge = RecordedForge::new(&observations);
        assert!(forge.body(&reference).is_err(), "no issue recorded");
        observations.issues.insert(reference.clone(), issue(None));
        let forge = RecordedForge::new(&observations);
        assert!(forge.body(&reference).is_err(), "no body recorded");
        observations.issues.insert(
            reference.clone(),
            Observed::Unavailable("HTTP 502".to_owned()),
        );
        let forge = RecordedForge::new(&observations);
        assert_eq!(
            forge.body(&reference),
            Ok(Observed::Unavailable("HTTP 502".to_owned()))
        );
    }

    #[test]
    fn an_unavailable_slot_answers_unavailable() {
        let observations = Observations {
            home_open_issues: Some(Observed::Unavailable("truncated".to_owned())),
            ..Observations::default()
        };
        let forge = RecordedForge::new(&observations);
        assert_eq!(
            forge.home_open_issues(),
            Ok(Observed::Unavailable("truncated".to_owned()))
        );
    }
}
