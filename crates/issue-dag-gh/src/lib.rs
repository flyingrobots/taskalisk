//! A `Forge` that reads GitHub through the `gh` command line (stub).

use std::ffi::OsStr;

use issue_dag_core::{
    CodeownersFile, Forge, Issue, IssueRef, Lookup, Missing, Observations, PullRequest, Repo,
};

/// The edit-history query.
pub const EDIT_HISTORY_QUERY: &str = "";

/// List and page limits.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Limits {
    /// Issues.
    pub issues: usize,
    /// Pull requests.
    pub pull_requests: usize,
    /// Edit-history pages.
    pub edit_history_pages: usize,
}

/// A failed read.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GhError;

impl GhError {
    /// Exit status.
    pub const EXIT_STATUS: i32 = 0;
    /// Code.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        ""
    }
}

impl std::fmt::Display for GhError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("")
    }
}

/// The forge.
#[derive(Debug)]
pub struct GhForge;

impl GhForge {
    /// New.
    #[must_use]
    pub fn new(_home: Repo) -> Self {
        Self
    }
    /// Program.
    #[must_use]
    pub fn program(self, _p: impl AsRef<OsStr>) -> Self {
        self
    }
    /// Env.
    #[must_use]
    pub fn env(self, _k: impl AsRef<OsStr>, _v: impl AsRef<OsStr>) -> Self {
        self
    }
    /// Limits.
    #[must_use]
    pub const fn limits(self, _l: Limits) -> Self {
        self
    }
    /// Failures.
    #[must_use]
    pub const fn failures(&self) -> Vec<GhError> {
        Vec::new()
    }
    /// Observations.
    #[must_use]
    pub fn observations(&self) -> Observations {
        Observations::default()
    }
}

fn missing<T>() -> Lookup<T> {
    Err(Missing { what: "stub".to_owned() })
}

impl Forge for GhForge {
    fn home_open_issues(&self) -> Lookup<Vec<IssueRef>> {
        missing()
    }
    fn home_open_pull_requests(&self) -> Lookup<Vec<PullRequest>> {
        missing()
    }
    fn issue(&self, _r: &IssueRef) -> Lookup<Issue> {
        missing()
    }
    fn permission(&self, _repo: &Repo, _login: &str) -> Lookup<Option<String>> {
        missing()
    }
    fn codeowners(&self, _repo: &Repo) -> Lookup<Option<CodeownersFile>> {
        missing()
    }
}
