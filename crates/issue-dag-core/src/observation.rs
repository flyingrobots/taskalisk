//! The run parameters and the observations a planning run reads (profile
//! rules I1 to I5; bundle rules OB3 to OB11), as domain values.

use core::fmt;
use std::collections::{BTreeMap, BTreeSet};

use crate::reference::{IssueRef, is_name};

/// The one trust policy this specification defines (profile rule I2).
pub const TRUST_POLICY: &str = "taskalisk/threat-model";

/// A repository `owner/repo`, held in canonical form: ASCII lower case
/// (format rule L1, bundle rule OB13).
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Repo {
    owner: String,
    name: String,
}

impl Repo {
    /// Reads `owner/repo`, folding it to lower case. Returns `None` when the
    /// text is not two names of rule L1 joined by `/`.
    #[must_use]
    pub fn parse(text: &str) -> Option<Self> {
        let (owner, name) = text.split_once('/')?;
        (is_name(owner) && is_name(name)).then(|| Self {
            owner: owner.to_ascii_lowercase(),
            name: name.to_ascii_lowercase(),
        })
    }

    /// The repository of a reference.
    #[must_use]
    pub fn of(reference: &IssueRef) -> Self {
        Self {
            owner: reference.owner().to_owned(),
            name: reference.repo().to_owned(),
        }
    }

    /// The owner, in ASCII lower case.
    #[must_use]
    pub fn owner(&self) -> &str {
        &self.owner
    }

    /// The repository name, in ASCII lower case.
    #[must_use]
    pub fn name(&self) -> &str {
        &self.name
    }
}

impl fmt::Display for Repo {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}/{}", self.owner, self.name)
    }
}

/// One observation slot (bundle rule OB4): what was observed, or why it
/// could not be observed. An unavailable observation is never an empty one.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Observed<T> {
    /// What was observed.
    Value(T),
    /// The observation could not be made, or could not be shown complete
    /// (profile rule I5); the text says why.
    Unavailable(String),
}

/// A slot the run needs and the observations do not hold (bundle rule
/// OB5). It is neither empty nor unavailable: the evidence is unusable.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Missing {
    /// The observation that was not recorded.
    pub what: String,
}

impl fmt::Display for Missing {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "the observations do not record {}", self.what)
    }
}

impl std::error::Error for Missing {}

/// The answer to one lookup: a slot, or [`Missing`] when it was never
/// recorded.
pub type Lookup<T> = Result<Observed<T>, Missing>;

/// An actor (bundle rule OB9).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Actor {
    /// The login as GitHub returns it.
    pub login: String,
    /// The actor type GitHub reports, such as `User` or `Bot`.
    pub actor_type: String,
}

/// The state of an issue.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum IssueState {
    /// `open`
    Open,
    /// `closed`
    Closed,
}

/// An issue body and the actor of every edit of it, the creation included,
/// observed together (bundle rule OB8). `None` is a deleted account.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Body {
    /// The body text.
    pub text: String,
    /// The editors, in order.
    pub editors: Vec<Option<Actor>>,
}

/// What a reference resolved to (bundle rule OB8).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Issue {
    /// The issue's address now; it differs from the reference read when the
    /// issue was transferred.
    pub address: IssueRef,
    /// Whether the reference resolves to a pull request.
    pub pull_request: bool,
    /// Open or closed.
    pub state: IssueState,
    /// The close reason as reported, such as `completed` or `not_planned`.
    pub state_reason: Option<String>,
    /// The author, or `None` for a deleted account.
    pub author: Option<Actor>,
    /// The author's association with the repository, as reported.
    pub author_association: Option<String>,
    /// The body and its editors.
    pub body: Observed<Body>,
}

/// An open pull request of the home repository (bundle rule OB7).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PullRequest {
    /// Its number.
    pub number: u64,
    /// Its repository, the home repository.
    pub repository: Repo,
    /// The repository of its head branch, when observed.
    pub head_repository: Option<Repo>,
    /// Whether the head branch is in another repository, when observed.
    pub cross_repository: Option<bool>,
    /// The author, or `None` for a deleted account.
    pub author: Option<Actor>,
    /// Whether it is a draft; unavailable when the flag observed was not a
    /// boolean (profile rule I5).
    pub draft: Observed<bool>,
    /// The issues it closes.
    pub closes: Vec<IssueRef>,
}

/// A CODEOWNERS file found in a repository (bundle rule OB11).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CodeownersFile {
    /// Where it was found.
    pub path: String,
    /// Its content.
    pub text: String,
}

/// The read scope (profile rule I1, bundle rule OB3).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReadScope {
    /// Owners whose every repository is in scope, in lower case.
    pub owners: BTreeSet<String>,
    /// Repositories in scope.
    pub repositories: BTreeSet<Repo>,
}

impl ReadScope {
    /// Whether a repository is in the read scope.
    #[must_use]
    pub fn contains(&self, repo: &Repo) -> bool {
        self.repositories.contains(repo) || self.owners.contains(repo.owner())
    }
}

/// The trust parameters of admission (admission rule AD1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TrustParameters {
    /// The name of the trust policy.
    pub policy: String,
    /// The allowlist: the logins the policy trusts by name.
    pub logins: Vec<String>,
    /// Whether the policy reads CODEOWNERS files.
    pub codeowners: bool,
}

/// The run parameters (profile rule I1, bundle rule OB3).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Parameters {
    /// The home repository `H`.
    pub home: Repo,
    /// The root references as given, unvalidated; empty when the run has
    /// none.
    pub roots: Vec<String>,
    /// The read scope; it includes `H`.
    pub read_scope: ReadScope,
    /// The trust parameters.
    pub trust: TrustParameters,
    /// Semaphore capacities, each positive.
    pub capacities: BTreeMap<String, u64>,
}
