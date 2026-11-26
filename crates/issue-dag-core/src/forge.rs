//! The ports the planner reads through, and an in-memory forge that answers
//! from recorded observations (decision 0001, section 2).

use std::collections::BTreeMap;

use crate::local::{AheadBehind, Branch, Worktree};
use crate::observation::{
    CodeownersFile, Issue, Lookup, Missing, Observed, Parameters, PullRequest, Repo,
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
///
/// The inventory reads the branches, the worktrees and how far each has
/// diverged from a base. A read that fails answers
/// [`Observed::Unavailable`], never an empty value.
pub trait LocalRepository {
    /// The names of the local branches.
    fn branch_names(&self) -> Observed<Vec<String>>;

    /// The local and remote-tracking branches with their tips; a symbolic
    /// ref such as `origin/HEAD` is not a branch.
    fn branches(&self) -> Observed<Vec<Branch>>;

    /// The worktrees, the main one first.
    fn worktrees(&self) -> Observed<Vec<Worktree>>;

    /// How far `revision` has diverged from `base`. Unavailable when either
    /// does not resolve to a commit.
    fn ahead_behind(&self, revision: &str, base: &str) -> Observed<AheadBehind>;
}

/// A local repository with no branches, for runs that read none.
#[derive(Clone, Copy, Debug, Default)]
pub struct NoLocalRepository;

impl LocalRepository for NoLocalRepository {
    fn branch_names(&self) -> Observed<Vec<String>> {
        Observed::Value(Vec::new())
    }

    fn branches(&self) -> Observed<Vec<Branch>> {
        Observed::Value(Vec::new())
    }

    fn worktrees(&self) -> Observed<Vec<Worktree>> {
        Observed::Value(Vec::new())
    }

    fn ahead_behind(&self, revision: &str, base: &str) -> Observed<AheadBehind> {
        Observed::Unavailable(format!(
            "no local repository: {revision} and {base} resolve to nothing"
        ))
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
    use super::{Forge, LocalRepository, NoLocalRepository, Observations, RecordedForge};
    use crate::observation::{Observed, Repo};
    use crate::reference::IssueRef;

    #[test]
    fn no_local_repository_answers_empty_lists_and_no_divergence() {
        let local = NoLocalRepository;
        assert_eq!(local.branch_names(), Observed::Value(Vec::new()));
        assert_eq!(local.branches(), Observed::Value(Vec::new()));
        assert_eq!(local.worktrees(), Observed::Value(Vec::new()));
        assert!(matches!(
            local.ahead_behind("HEAD", "main"),
            Observed::Unavailable(_)
        ));
    }

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
