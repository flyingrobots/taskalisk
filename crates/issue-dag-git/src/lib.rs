//! The git adapter: the [`LocalRepository`] port answered by running `git`.
//!
//! Every read runs `git -C <path>` with an argument list, never a shell,
//! and parses a machine format: `for-each-ref` with NUL-separated fields,
//! `worktree list --porcelain -z`, `status --porcelain -z` and
//! `rev-list --left-right --count`. The variables that would point git at
//! another repository (`GIT_DIR`, `GIT_WORK_TREE` and the like) are removed,
//! so a run inside a hook reads the repository it was given.
//!
//! It fails closed. [`GitRepository::open`] refuses a path that is not a
//! repository, and each `read_*` method returns a [`GitError`] when git
//! fails or answers in a shape it cannot read; the port methods answer
//! [`Observed::Unavailable`] with that error's text, never an empty value.
//! The binary reports a `GitError` as `git.command_failed` and exits 2.

use core::fmt;
use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use issue_dag_core::{
    AheadBehind, Branch, BranchScope, Checkout, LocalRepository, Observed, Worktree,
};

/// The variables that select a repository other than the one at `-C`.
const REPOSITORY_VARIABLES: &[&str] = &[
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
    "GIT_CEILING_DIRECTORIES",
];

/// Why a read of the local repository failed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GitError {
    /// The path is not inside a git repository, or does not exist.
    NotARepository {
        /// The path given.
        path: PathBuf,
        /// What git said.
        stderr: String,
    },
    /// `git` could not be started.
    Spawn {
        /// The command line, for the report.
        command: String,
        /// The operating system's error.
        message: String,
    },
    /// `git` exited unsuccessfully.
    Failed {
        /// The command line, for the report.
        command: String,
        /// The exit status, `None` when a signal ended it.
        status: Option<i32>,
        /// What git said.
        stderr: String,
    },
    /// `git` succeeded but its output could not be read.
    Unreadable {
        /// The command line, for the report.
        command: String,
        /// What was wrong with the output.
        why: String,
    },
}

impl fmt::Display for GitError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotARepository { path, stderr } => {
                write!(f, "{} is not a git repository: {stderr}", path.display())
            }
            Self::Spawn { command, message } => {
                write!(f, "{command} could not be started: {message}")
            }
            Self::Failed {
                command,
                status: Some(code),
                stderr,
            } => write!(f, "{command} exited with status {code}: {stderr}"),
            Self::Failed {
                command,
                status: None,
                stderr,
            } => write!(f, "{command} was ended by a signal: {stderr}"),
            Self::Unreadable { command, why } => {
                write!(
                    f,
                    "{command} answered in a shape that cannot be read: {why}"
                )
            }
        }
    }
}

impl std::error::Error for GitError {}

/// A local repository read through `git`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GitRepository {
    path: PathBuf,
}

impl GitRepository {
    /// Opens the repository at or above `path` (`git rev-parse --git-dir`).
    ///
    /// # Errors
    ///
    /// [`GitError::NotARepository`] when `path` is not in a repository or
    /// does not exist; [`GitError::Spawn`] when `git` cannot be started.
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, GitError> {
        let path = path.into();
        match git(&path, &["rev-parse", "--git-dir"], None) {
            Ok(_) => Ok(Self { path }),
            Err(GitError::Failed { stderr, .. }) => Err(GitError::NotARepository { path, stderr }),
            Err(other) => Err(other),
        }
    }

    /// The path the repository was opened at.
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// The names of the local branches, in byte order.
    ///
    /// # Errors
    ///
    /// A [`GitError`] when git fails or its output cannot be read.
    pub fn read_branch_names(&self) -> Result<Vec<String>, GitError> {
        Ok(self
            .read_branches()?
            .into_iter()
            .filter(|branch| branch.scope == BranchScope::Local)
            .map(|branch| branch.name)
            .collect())
    }

    /// The local and remote-tracking branches, ordered by ref name
    /// (`git for-each-ref refs/heads refs/remotes`). Symbolic refs such as
    /// `origin/HEAD` are left out.
    ///
    /// # Errors
    ///
    /// A [`GitError`] when git fails or its output cannot be read.
    pub fn read_branches(&self) -> Result<Vec<Branch>, GitError> {
        let args = [
            "for-each-ref",
            "--sort=refname",
            "--format=%(refname)%00%(symref)%00%(objectname)%00%(contents:subject)",
            "refs/heads",
            "refs/remotes",
        ];
        let out = text(&self.path, &args, git(&self.path, &args, None)?)?;
        let unreadable = |why: String| GitError::Unreadable {
            command: command_line(&self.path, &args),
            why,
        };
        let mut branches = Vec::new();
        for line in out.lines().filter(|line| !line.is_empty()) {
            let fields: Vec<&str> = line.split('\0').collect();
            let [refname, symref, head, subject] = fields[..] else {
                return Err(unreadable(format!("{} fields, not 4", fields.len())));
            };
            if !symref.is_empty() {
                continue;
            }
            let (scope, name) = if let Some(name) = refname.strip_prefix("refs/heads/") {
                (BranchScope::Local, name)
            } else if let Some(name) = refname.strip_prefix("refs/remotes/") {
                (BranchScope::Remote, name)
            } else {
                return Err(unreadable(format!("an unexpected ref {refname}")));
            };
            branches.push(Branch {
                scope,
                name: name.to_owned(),
                head: head.to_owned(),
                tip_subject: subject.to_owned(),
            });
        }
        Ok(branches)
    }

    /// The worktrees, the main one first (`git worktree list --porcelain
    /// -z`), each with its dirty state (`git status --porcelain -z` in the
    /// worktree) when its directory exists and it is not prunable.
    ///
    /// # Errors
    ///
    /// A [`GitError`] when git fails, for the listing or for any worktree's
    /// status, or its output cannot be read.
    pub fn read_worktrees(&self) -> Result<Vec<Worktree>, GitError> {
        let args = ["worktree", "list", "--porcelain", "-z"];
        let out = text(&self.path, &args, git(&self.path, &args, None)?)?;
        let records = parse_worktrees(&out).map_err(|why| GitError::Unreadable {
            command: command_line(&self.path, &args),
            why,
        })?;
        records
            .into_iter()
            .map(|record| {
                let dir = Path::new(&record.path);
                let path_exists = dir.is_dir();
                let dirty = if path_exists && !record.prunable && record.checkout != Checkout::Bare
                {
                    Some(is_dirty(dir)?)
                } else {
                    None
                };
                Ok(Worktree {
                    path: record.path,
                    path_exists,
                    head: record.head,
                    checkout: record.checkout,
                    locked: record.locked,
                    prunable: record.prunable,
                    dirty,
                })
            })
            .collect()
    }

    /// How far `revision` has diverged from `base` (`git rev-list
    /// --left-right --count`). Both are read as revisions, never options.
    ///
    /// # Errors
    ///
    /// A [`GitError`] when either does not resolve to a commit, git fails,
    /// or its output cannot be read.
    pub fn read_ahead_behind(&self, revision: &str, base: &str) -> Result<AheadBehind, GitError> {
        let range = format!("{revision}...{base}");
        let args = [
            "rev-list",
            "--left-right",
            "--count",
            "--end-of-options",
            range.as_str(),
        ];
        let out = text(&self.path, &args, git(&self.path, &args, None)?)?;
        let unreadable = || GitError::Unreadable {
            command: command_line(&self.path, &args),
            why: format!("{:?} is not two counts", out.trim_end()),
        };
        let (ahead, behind) = out.trim_end().split_once('\t').ok_or_else(unreadable)?;
        Ok(AheadBehind {
            ahead: ahead.parse().map_err(|_| unreadable())?,
            behind: behind.parse().map_err(|_| unreadable())?,
        })
    }
}

fn observed<T>(read: Result<T, GitError>) -> Observed<T> {
    match read {
        Ok(value) => Observed::Value(value),
        Err(error) => Observed::Unavailable(error.to_string()),
    }
}

impl LocalRepository for GitRepository {
    fn branch_names(&self) -> Observed<Vec<String>> {
        observed(self.read_branch_names())
    }

    fn branches(&self) -> Observed<Vec<Branch>> {
        observed(self.read_branches())
    }

    fn worktrees(&self) -> Observed<Vec<Worktree>> {
        observed(self.read_worktrees())
    }

    fn ahead_behind(&self, revision: &str, base: &str) -> Observed<AheadBehind> {
        observed(self.read_ahead_behind(revision, base))
    }
}

/// One record of `git worktree list --porcelain -z`.
#[derive(Debug, PartialEq, Eq)]
struct Record {
    path: String,
    head: Option<String>,
    checkout: Checkout,
    locked: bool,
    prunable: bool,
}

/// Reads the porcelain records: attributes end with NUL, a record ends
/// with an empty attribute. Unknown attributes are skipped, so a newer git
/// that adds one is still read.
fn parse_worktrees(out: &str) -> Result<Vec<Record>, String> {
    let mut records = Vec::new();
    let mut current: Option<Record> = None;
    if out.is_empty() {
        return Err("no worktree listed, not even the main one".to_owned());
    }
    let mut attributes = out.split('\0');
    // The output ends with the terminator of the last record, so the last
    // split piece is empty and belongs to no record.
    if out.ends_with('\0') {
        let _ = attributes.next_back();
    }
    for attribute in attributes {
        if attribute.is_empty() {
            records.push(current.take().ok_or("an empty record")?);
            continue;
        }
        let (key, value) = attribute.split_once(' ').unwrap_or((attribute, ""));
        if key == "worktree" {
            if current.is_some() {
                return Err("a record with two worktree lines".to_owned());
            }
            current = Some(Record {
                path: value.to_owned(),
                head: None,
                checkout: Checkout::Detached,
                locked: false,
                prunable: false,
            });
            continue;
        }
        let record = current
            .as_mut()
            .ok_or_else(|| format!("{key} before any worktree line"))?;
        match key {
            "HEAD" => record.head = Some(value.to_owned()),
            "branch" => {
                let name = value
                    .strip_prefix("refs/heads/")
                    .ok_or_else(|| format!("a branch outside refs/heads: {value}"))?;
                record.checkout = Checkout::Branch(name.to_owned());
            }
            "detached" => record.checkout = Checkout::Detached,
            "bare" => record.checkout = Checkout::Bare,
            "locked" => record.locked = true,
            "prunable" => record.prunable = true,
            _ => {}
        }
    }
    if current.is_some() {
        return Err("the last record is not terminated".to_owned());
    }
    if records.is_empty() {
        return Err("no worktree listed, not even the main one".to_owned());
    }
    Ok(records)
}

/// Whether a worktree has changes, untracked files included. Discovery is
/// held to the worktree itself, so a worktree whose `.git` is gone is an
/// error, never a read of the repository above it.
fn is_dirty(dir: &Path) -> Result<bool, GitError> {
    let args = [
        "--no-optional-locks",
        "status",
        "--porcelain",
        "-z",
        "--untracked-files=normal",
        "--ignore-submodules=none",
    ];
    let ceiling = dir.parent().map(Path::as_os_str);
    Ok(!git(dir, &args, ceiling)?.is_empty())
}

fn command_line(dir: &Path, args: &[&str]) -> String {
    format!("git -C {} {}", dir.display(), args.join(" "))
}

fn text(dir: &Path, args: &[&str], bytes: Vec<u8>) -> Result<String, GitError> {
    String::from_utf8(bytes).map_err(|_| GitError::Unreadable {
        command: command_line(dir, args),
        why: "the output is not UTF-8".to_owned(),
    })
}

/// Runs `git -C dir args` with no shell, no prompt, a fixed locale and no
/// repository-selecting variables; returns its standard output.
fn git(dir: &Path, args: &[&str], ceiling: Option<&OsStr>) -> Result<Vec<u8>, GitError> {
    let mut command = Command::new("git");
    command
        .arg("-C")
        .arg(dir)
        .args(args)
        .stdin(Stdio::null())
        .env("LC_ALL", "C")
        .env("GIT_TERMINAL_PROMPT", "0");
    for variable in REPOSITORY_VARIABLES {
        command.env_remove(variable);
    }
    if let Some(ceiling) = ceiling {
        command.env("GIT_CEILING_DIRECTORIES", OsString::from(ceiling));
    }
    let output = command.output().map_err(|error| GitError::Spawn {
        command: command_line(dir, args),
        message: error.to_string(),
    })?;
    if output.status.success() {
        Ok(output.stdout)
    } else {
        Err(GitError::Failed {
            command: command_line(dir, args),
            status: output.status.code(),
            stderr: String::from_utf8_lossy(&output.stderr).trim().to_owned(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{Checkout, Record, parse_worktrees};

    #[test]
    fn parses_porcelain_records_with_spaces_and_reasons() {
        let out = "worktree /r\0HEAD abc\0branch refs/heads/main\0\0\
                   worktree /w with space\0HEAD def\0detached\0locked a reason\0prunable gone\0\0\
                   worktree /bare\0bare\0\0";
        assert_eq!(
            parse_worktrees(out),
            Ok(vec![
                Record {
                    path: "/r".to_owned(),
                    head: Some("abc".to_owned()),
                    checkout: Checkout::Branch("main".to_owned()),
                    locked: false,
                    prunable: false,
                },
                Record {
                    path: "/w with space".to_owned(),
                    head: Some("def".to_owned()),
                    checkout: Checkout::Detached,
                    locked: true,
                    prunable: true,
                },
                Record {
                    path: "/bare".to_owned(),
                    head: None,
                    checkout: Checkout::Bare,
                    locked: false,
                    prunable: false,
                },
            ])
        );
    }

    #[test]
    fn refuses_truncated_or_malformed_output() {
        assert!(parse_worktrees("worktree /r\0HEAD abc\0").is_err());
        assert!(parse_worktrees("HEAD abc\0\0").is_err());
        assert!(parse_worktrees("\0").is_err());
        assert!(parse_worktrees("worktree /r\0branch refs/tags/x\0\0").is_err());
    }

    #[test]
    fn an_empty_listing_is_refused_never_empty() {
        // git always lists the main worktree.
        assert!(parse_worktrees("").is_err());
    }
}
