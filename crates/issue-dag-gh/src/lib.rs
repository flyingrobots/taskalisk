//! A [`Forge`] that reads GitHub through the `gh` command line (decision
//! 0001, section 2).
//!
//! Every read runs `gh` with an argument vector, never a shell string; the
//! program defaults to `gh` on `PATH`. The reads are the Python compiler's:
//! the REST issue list and issue, the edit-history GraphQL query with its
//! pagination guards, `gh pr list` with closing references, the
//! collaborator permission and the CODEOWNERS file, with the same limits.
//! The edit-history query runs only when [`Forge::body`] is asked, which the
//! planner does only for an issue whose author is trusted, so an issue a
//! stranger wrote costs no further query (threat model C15).
//!
//! The forge fails closed. A read that fails, answers in the wrong shape, or
//! fills its list limit is a [`GhError`], never an empty answer: the slot is
//! answered unavailable with the error as its reason, so a run that needs it
//! is incomplete (profile rule F1, exit 2), and the error is kept for the
//! run's report ([`GhForge::failures`]). HTTP 404 means "none" only where the
//! Python compiler reads it so: a collaborator permission (not a
//! collaborator), a CODEOWNERS path (try the next), and an issue (it
//! resolves to nothing the planner can see, profile rule D10).
//!
//! Each slot is read once: a second lookup answers what the first observed,
//! and [`GhForge::observations`] is the recording of every slot read, which
//! the core's [`issue_dag_core::RecordedForge`] replays.

mod error;
mod read;
mod run;

use std::cell::RefCell;
use std::ffi::{OsStr, OsString};

use issue_dag_core::{
    Body, CodeownersFile, Forge, Issue, IssueRef, Lookup, Observations, Observed, PullRequest, Repo,
};

pub use error::GhError;
pub use read::{CODEOWNERS_PATHS, EDIT_HISTORY_QUERY};
use run::Runner;

/// The bounds a read refuses to pass. A list that fills its limit may be
/// truncated, and is an error (threat model C15).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Limits {
    /// The open issues of the home repository, pull requests excluded.
    pub issues: usize,
    /// The open pull requests of the home repository (`gh pr list --limit`).
    pub pull_requests: usize,
    /// The pages of 100 edits of one body's edit history.
    pub edit_history_pages: usize,
}

impl Default for Limits {
    /// The Python compiler's: `GH_ISSUE_LIST_LIMIT`, `GH_PR_LIST_LIMIT` and
    /// `EDIT_HISTORY_MAX_PAGES`.
    fn default() -> Self {
        Self {
            issues: 1000,
            pull_requests: 500,
            edit_history_pages: 1000,
        }
    }
}

/// The forge of a home repository, read through `gh`.
#[derive(Debug)]
pub struct GhForge {
    home: Repo,
    runner: Runner,
    limits: Limits,
    read: RefCell<Observations>,
    failures: RefCell<Vec<GhError>>,
}

impl GhForge {
    /// A forge for the home repository `home`, running `gh` from `PATH`
    /// with the default [`Limits`].
    #[must_use]
    pub fn new(home: Repo) -> Self {
        Self {
            home,
            runner: Runner {
                program: OsString::from("gh"),
                env: Vec::new(),
            },
            limits: Limits::default(),
            read: RefCell::new(Observations::default()),
            failures: RefCell::new(Vec::new()),
        }
    }

    /// Runs `program` in place of `gh`: a name looked up on `PATH`, or a path.
    #[must_use]
    pub fn program(mut self, program: impl AsRef<OsStr>) -> Self {
        program.as_ref().clone_into(&mut self.runner.program);
        self
    }

    /// Gives `gh` the variable `key` with `value`, on top of this process's
    /// environment. A `PATH` given here is also where `gh` is looked up.
    ///
    /// `gh` always runs without `GH_FORCE_TTY`, `CLICOLOR_FORCE`, `GH_DEBUG`
    /// and `DEBUG`, and with `GH_PROMPT_DISABLED=1`, `NO_COLOR=1`,
    /// `GH_NO_UPDATE_NOTIFIER=1` and `GH_PAGER=cat`; a variable given here
    /// cannot change those.
    #[must_use]
    pub fn env(mut self, key: impl AsRef<OsStr>, value: impl AsRef<OsStr>) -> Self {
        self.runner
            .env
            .push((key.as_ref().to_owned(), value.as_ref().to_owned()));
        self
    }

    /// Reads with `limits` in place of the defaults.
    #[must_use]
    pub const fn limits(mut self, limits: Limits) -> Self {
        self.limits = limits;
        self
    }

    /// Every read that failed, in order. Not empty means the run that read
    /// through this forge exits with [`GhError::EXIT_STATUS`].
    #[must_use]
    pub fn failures(&self) -> Vec<GhError> {
        self.failures.borrow().clone()
    }

    /// Every slot read so far, as recorded observations (bundle section 2).
    #[must_use]
    pub fn observations(&self) -> Observations {
        self.read.borrow().clone()
    }

    /// The slot of a read: its value, or unavailable with the failure kept.
    fn settle<T>(&self, result: Result<T, GhError>) -> Observed<T> {
        match result {
            Ok(value) => Observed::Value(value),
            Err(error) => {
                let why = error.to_string();
                self.failures.borrow_mut().push(error);
                Observed::Unavailable(why)
            }
        }
    }
}

impl Forge for GhForge {
    fn home_open_issues(&self) -> Lookup<Vec<IssueRef>> {
        let cached = self.read.borrow().home_open_issues.clone();
        let slot = cached.unwrap_or_else(|| {
            self.settle(read::home_open_issues(
                &self.runner,
                &self.home,
                self.limits,
            ))
        });
        self.read.borrow_mut().home_open_issues = Some(slot.clone());
        Ok(slot)
    }

    fn home_open_pull_requests(&self) -> Lookup<Vec<PullRequest>> {
        let cached = self.read.borrow().home_open_pull_requests.clone();
        let slot = cached.unwrap_or_else(|| {
            self.settle(read::home_open_pull_requests(
                &self.runner,
                &self.home,
                self.limits,
            ))
        });
        self.read.borrow_mut().home_open_pull_requests = Some(slot.clone());
        Ok(slot)
    }

    /// The REST issue alone; its body is [`Forge::body`]'s read.
    fn issue(&self, reference: &IssueRef) -> Lookup<Issue> {
        let cached = self.read.borrow().issues.get(reference).cloned();
        let slot = cached.unwrap_or_else(|| {
            let slot = match read::issue(&self.runner, reference) {
                Ok(slot) => slot,
                Err(error) => self.settle(Err(error)),
            };
            self.read
                .borrow_mut()
                .issues
                .insert(reference.clone(), slot.clone());
            slot
        });
        Ok(match slot {
            Observed::Value(issue) => Observed::Value(Issue {
                body: None,
                ..issue
            }),
            Observed::Unavailable(why) => Observed::Unavailable(why),
        })
    }

    /// The edit-history query, run only when the body is asked for (threat
    /// model C15), once; the body is recorded in the issue's slot.
    fn body(&self, reference: &IssueRef) -> Lookup<Body> {
        let issue = match self.issue(reference)? {
            Observed::Value(issue) => issue,
            Observed::Unavailable(why) => return Ok(Observed::Unavailable(why)),
        };
        let cached = match self.read.borrow().issues.get(reference) {
            Some(Observed::Value(recorded)) => recorded.body.clone(),
            _ => None,
        };
        if let Some(slot) = cached {
            return Ok(slot);
        }
        let slot = read::body_not_read(reference, &issue).map_or_else(
            || self.settle(read::edit_history(&self.runner, reference, self.limits)),
            Observed::Unavailable,
        );
        if let Some(Observed::Value(recorded)) = self.read.borrow_mut().issues.get_mut(reference) {
            recorded.body = Some(slot.clone());
        }
        Ok(slot)
    }

    fn permission(&self, repo: &Repo, login: &str) -> Lookup<Option<String>> {
        let cached = self
            .read
            .borrow()
            .permissions
            .get(repo)
            .and_then(|table| table.get(login))
            .cloned();
        let slot =
            cached.unwrap_or_else(|| self.settle(read::permission(&self.runner, repo, login)));
        self.read
            .borrow_mut()
            .permissions
            .entry(repo.clone())
            .or_default()
            .insert(login.to_owned(), slot.clone());
        Ok(slot)
    }

    fn codeowners(&self, repo: &Repo) -> Lookup<Option<CodeownersFile>> {
        let cached = self
            .read
            .borrow()
            .codeowners
            .as_ref()
            .and_then(|files| files.get(repo))
            .cloned();
        let slot = cached.unwrap_or_else(|| self.settle(read::codeowners(&self.runner, repo)));
        self.read
            .borrow_mut()
            .codeowners
            .get_or_insert_default()
            .insert(repo.clone(), slot.clone());
        Ok(slot)
    }
}
