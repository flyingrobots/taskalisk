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
use std::collections::BTreeMap;
use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};

use issue_dag_core::{
    Body, CodeownersFile, Forge, Issue, IssueRef, Lookup, Observations, Observed, PullRequest, Repo,
};

pub use error::GhError;
use read::Label;
pub use read::{CODEOWNERS_PATHS, EDIT_HISTORY_QUERY};
use run::Runner;

/// What the reads returned only to be shown, never to plan from.
///
/// The title and web URL of each issue read, under the reference read,
/// kept from the answers the forge already has, so showing them costs no
/// query.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Shown {
    /// The title of each issue read, as GitHub returned it.
    pub titles: BTreeMap<IssueRef, String>,
    /// The web URL (`html_url`) of each issue read.
    pub urls: BTreeMap<IssueRef, String>,
}

impl Shown {
    fn keep(&mut self, reference: &IssueRef, label: Label) {
        if let Some(title) = label.title {
            self.titles.insert(reference.clone(), title);
        }
        if let Some(url) = label.url {
            self.urls.insert(reference.clone(), url);
        }
    }
}

/// The repository `gh` resolves from `dir` (`gh repo view`).
///
/// It runs `program` with `env` on top of this process's environment, as
/// [`GhForge`] runs it, and answers the home repository of a run on
/// `--repo dir`, found before a forge for it exists.
///
/// # Errors
///
/// A [`GhError`] when `gh` fails or does not answer `owner/name`.
pub fn repository_of(
    program: impl AsRef<OsStr>,
    env: &[(OsString, OsString)],
    dir: &Path,
) -> Result<Repo, GhError> {
    read::repository(&Runner {
        program: program.as_ref().to_owned(),
        env: env.to_vec(),
        dir: Some(dir.to_owned()),
    })
}

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
    shown: RefCell<Shown>,
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
                dir: None,
            },
            limits: Limits::default(),
            read: RefCell::new(Observations::default()),
            failures: RefCell::new(Vec::new()),
            shown: RefCell::new(Shown::default()),
        }
    }

    /// Runs `gh` in `dir`, as the Python compiler runs it in `--repo`, so
    /// that `gh` sees that repository's host and remotes.
    #[must_use]
    pub fn current_dir(mut self, dir: impl Into<PathBuf>) -> Self {
        self.runner.dir = Some(dir.into());
        self
    }

    /// The repository `gh` resolves from `dir` (`gh repo view --json
    /// nameWithOwner`): the home repository of a run on `--repo dir`. Run
    /// with this forge's program and environment, before a forge for that
    /// home exists.
    ///
    /// # Errors
    ///
    /// A [`GhError`] when `gh` fails or does not answer `owner/name`.
    pub fn repository_of(&self, dir: &Path) -> Result<Repo, GhError> {
        repository_of(&self.runner.program, &self.runner.env, dir)
    }

    /// The title and URL of every issue read so far, to be shown: never an
    /// input to a plan. Makes no query.
    #[must_use]
    pub fn shown(&self) -> Shown {
        self.shown.borrow().clone()
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
        if let Some(slot) = cached {
            return Ok(slot);
        }
        let listed = read::home_open_issues(&self.runner, &self.home, self.limits).map(|listed| {
            // Each listed issue is read: its own lookup makes no query.
            let mut read = self.read.borrow_mut();
            let mut shown = self.shown.borrow_mut();
            listed
                .into_iter()
                .map(|(reference, issue, label)| {
                    if let std::collections::btree_map::Entry::Vacant(slot) =
                        read.issues.entry(reference.clone())
                    {
                        slot.insert(Observed::Value(issue));
                        shown.keep(&reference, label);
                    }
                    reference
                })
                .collect()
        });
        let slot = self.settle(listed);
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
                Ok(Observed::Value((issue, label))) => {
                    self.shown.borrow_mut().keep(reference, label);
                    Observed::Value(issue)
                }
                Ok(Observed::Unavailable(why)) => Observed::Unavailable(why),
                Err(error) => self.settle(Err(error)),
            };
            self.read
                .borrow_mut()
                .issues
                .insert(reference.clone(), slot.clone());
            slot
        });
        Ok(slot)
    }

    /// The edit-history query, run only when the body is asked for, once;
    /// the body is recorded in [`Observations::bodies`].
    ///
    /// Ask for it only after the issue's author is admitted: asking for a
    /// stranger's body spends the query threat model C15 saves. The planner
    /// is the only caller.
    fn body(&self, reference: &IssueRef) -> Lookup<Body> {
        let issue = match self.issue(reference)? {
            Observed::Value(issue) => issue,
            Observed::Unavailable(why) => return Ok(Observed::Unavailable(why)),
        };
        let cached = self.read.borrow().bodies.get(reference).cloned();
        if let Some(slot) = cached {
            return Ok(slot);
        }
        let slot = read::body_not_read(reference, &issue).map_or_else(
            || self.settle(read::edit_history(&self.runner, reference, self.limits)),
            Observed::Unavailable,
        );
        self.read
            .borrow_mut()
            .bodies
            .insert(reference.clone(), slot.clone());
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
