//! The git adapter: the [`LocalRepository`] port answered by running `git`.
//!
//! [`GitRepository::open`] takes the top level of a work tree and records
//! its git directory and work tree; every read then runs
//! `git --git-dir <dir> --work-tree <tree>` with an argument list, never a
//! shell, and never discovers a repository again. Each read parses a
//! machine format: `for-each-ref` with NUL-separated fields,
//! `worktree list --porcelain -z`, `status --porcelain -z` and
//! `rev-list --left-right --count`.
//!
//! It only reads. Every call passes `--no-optional-locks`, so `status`
//! never rewrites the index, and turns off `core.fsmonitor` and
//! `core.untrackedCache`, so a configured monitor command never runs and a
//! stale cache never hides an untracked file. One configured command can
//! still run: a clean filter (`filter.<driver>.clean`) that `status` uses
//! to compare a file whose stat data changed. That is accepted: a filter
//! command comes only from the user's own local or global configuration,
//! which a clone cannot set, so it runs with the same trust as the user's
//! own `git status`. Every inherited `GIT_*` variable is removed (`GIT_DIR`, `GIT_CONFIG_*`,
//! `GIT_CEILING_DIRECTORIES`, `GIT_NO_REPLACE_OBJECTS` and the rest), so a
//! run inside a hook, or under a caller's injected configuration, reads the
//! repository it was given as that repository configures it.
//!
//! It fails closed, in two shapes. Each `read_*` method returns a
//! [`GitError`] when git fails or answers in a shape it cannot read; a
//! caller that needs the kind of failure (the binary, to report
//! `git.command_failed`) calls these. The [`LocalRepository`] port carries
//! no kind: a port method answers [`Observed::Unavailable`] with the
//! error's text, never an empty value, and the run that reads it is
//! incomplete (the core's `Forge` and `LocalRepository` documentation).

use core::fmt;
use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use issue_dag_core::{
    AheadBehind, Branch, BranchScope, Checkout, LocalRepository, Observed, Worktree,
};

/// The options every call starts with: take no optional lock (so `status`
/// never rewrites the index), and run no configured file-system monitor or
/// untracked cache (a configured `core.fsmonitor` is a command).
const READ_ONLY_OPTIONS: &[&str] = &[
    "--no-optional-locks",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.untrackedCache=false",
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
    /// The path is inside a work tree but is not its top level (a
    /// subdirectory, or the `.git` directory itself).
    NotTopLevel {
        /// The path given.
        path: PathBuf,
        /// The top level of the work tree it is in, as git reports it.
        top_level: PathBuf,
    },
    /// A listed worktree's directory holds the `.git` of another
    /// repository: its directory was replaced after the worktree was added.
    ForeignWorktree {
        /// The worktree's directory, as listed.
        worktree: PathBuf,
        /// The common git directory its `.git` belongs to.
        common_dir: PathBuf,
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
            Self::NotTopLevel { path, top_level } => write!(
                f,
                "{} is not the top level of a work tree; the top level is {}",
                path.display(),
                top_level.display()
            ),
            Self::ForeignWorktree {
                worktree,
                common_dir,
            } => write!(
                f,
                "the worktree {} holds the .git of another repository ({})",
                worktree.display(),
                common_dir.display()
            ),
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

/// Where a call points git: a directory to discover from (only to open),
/// or a recorded git directory and work tree (every read).
#[derive(Clone, Copy)]
enum At<'a> {
    Discover(&'a Path),
    Recorded {
        git_dir: &'a Path,
        work_tree: &'a Path,
    },
}

/// A local repository read through `git`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GitRepository {
    work_tree: PathBuf,
    git_dir: PathBuf,
    /// The common git directory, canonical: the main repository's git
    /// directory, which every worktree's own git directory belongs to.
    common_dir: PathBuf,
}

impl GitRepository {
    /// Opens the repository whose work tree has its top level at `path`, a
    /// main or a linked worktree
    /// (`git rev-parse --absolute-git-dir --show-toplevel --git-common-dir`),
    /// and records its git directory, work tree and common git directory.
    ///
    /// `path` must be the top level itself. A subdirectory of a work tree,
    /// a `.git` directory and a bare repository are refused, so a plain
    /// directory inside some other repository never opens that one. Every
    /// later read runs against the recorded git directory and work tree
    /// (`--git-dir`, `--work-tree`) and never discovers again: when the
    /// git directory is gone, the read fails; it never reads a repository
    /// above.
    ///
    /// # Errors
    ///
    /// [`GitError::NotARepository`] when `path` is not in a work tree, is
    /// in a bare repository or does not exist; [`GitError::NotTopLevel`]
    /// when it is inside a work tree but not its top level;
    /// [`GitError::Spawn`] when `git` cannot be started;
    /// [`GitError::Unreadable`] when git's answer cannot be read.
    pub fn open(path: impl Into<PathBuf>) -> Result<Self, GitError> {
        let path = path.into();
        let at = At::Discover(&path);
        let args = [
            "rev-parse",
            "--absolute-git-dir",
            "--show-toplevel",
            "--path-format=absolute",
            "--git-common-dir",
        ];
        let out = match git(at, &args) {
            Ok(out) => text(at, &args, out)?,
            Err(GitError::Failed { stderr, .. }) => {
                return Err(GitError::NotARepository { path, stderr });
            }
            Err(other) => return Err(other),
        };
        let unreadable = |why: String| GitError::Unreadable {
            command: command_line(at, &args),
            why,
        };
        let lines: Vec<&str> = out.lines().collect();
        let [git_dir, top_level, common_dir] = lines[..] else {
            return Err(unreadable(format!("{} lines, not 3", lines.len())));
        };
        let (git_dir, top_level) = (PathBuf::from(git_dir), PathBuf::from(top_level));
        let resolved = (
            path.canonicalize(),
            top_level.canonicalize(),
            Path::new(common_dir).canonicalize(),
        );
        let (given, top, common_dir) = match resolved {
            (Ok(given), Ok(top), Ok(common)) => (given, top, common),
            (Err(error), _, _) | (_, Err(error), _) | (_, _, Err(error)) => {
                return Err(unreadable(format!("a path cannot be resolved: {error}")));
            }
        };
        if given != top {
            return Err(GitError::NotTopLevel { path, top_level });
        }
        Ok(Self {
            work_tree: top_level,
            git_dir,
            common_dir,
        })
    }

    /// The top level of the work tree, as git reported it at
    /// [`open`](Self::open).
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.work_tree
    }

    /// The git directory recorded at [`open`](Self::open); for a linked
    /// worktree, its own directory under the main repository's.
    #[must_use]
    pub fn git_dir(&self) -> &Path {
        &self.git_dir
    }

    fn at(&self) -> At<'_> {
        At::Recorded {
            git_dir: &self.git_dir,
            work_tree: &self.work_tree,
        }
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
        let at = self.at();
        let out = text(at, &args, git(at, &args)?)?;
        let unreadable = |why: String| GitError::Unreadable {
            command: command_line(at, &args),
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
    /// Each worktree's `status` runs against that worktree's own `.git`,
    /// after checking that it belongs to the opened repository (the same
    /// common git directory). For a submodule or a repository made with
    /// `--separate-git-dir`, git lists the main worktree at its git
    /// directory; its dirty state is read through the work tree recorded at
    /// [`open`](Self::open) when that is the main worktree, and is unknown
    /// (`None`) when a linked worktree was opened.
    ///
    /// # Errors
    ///
    /// [`GitError::ForeignWorktree`] when a listed worktree's directory
    /// holds another repository's `.git`; another [`GitError`] when git
    /// fails, for the listing or for any worktree's status, or its output
    /// cannot be read.
    pub fn read_worktrees(&self) -> Result<Vec<Worktree>, GitError> {
        let args = ["worktree", "list", "--porcelain", "-z"];
        let at = self.at();
        let out = text(at, &args, git(at, &args)?)?;
        let records = parse_worktrees(&out).map_err(|why| GitError::Unreadable {
            command: command_line(at, &args),
            why,
        })?;
        records
            .into_iter()
            .enumerate()
            .map(|(index, record)| {
                let dir = Path::new(&record.path);
                let path_exists = dir.is_dir();
                let dirty = if path_exists && !record.prunable && record.checkout != Checkout::Bare
                {
                    self.dirty(dir, index == 0)?
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

    /// The dirty state of one listed worktree, read against its own `.git`
    /// once that is known to belong to this repository.
    fn dirty(&self, dir: &Path, main: bool) -> Result<Option<bool>, GitError> {
        if main && dir.canonicalize().ok().as_ref() == Some(&self.common_dir) {
            // Listed at its git directory: the work tree is known only when
            // it is the one opened.
            let opened_main = self.git_dir.canonicalize().ok().as_ref() == Some(&self.common_dir);
            return if opened_main {
                is_dirty(self.at()).map(Some)
            } else {
                Ok(None)
            };
        }
        let git_dir = dir.join(".git");
        let at = At::Recorded {
            git_dir: &git_dir,
            work_tree: dir,
        };
        let args = ["rev-parse", "--path-format=absolute", "--git-common-dir"];
        let out = text(at, &args, git(at, &args)?)?;
        let common_dir = Path::new(out.trim_end_matches('\n'));
        let unreadable = |error: std::io::Error| GitError::Unreadable {
            command: command_line(at, &args),
            why: format!("the common git directory cannot be resolved: {error}"),
        };
        if common_dir.canonicalize().map_err(unreadable)? != self.common_dir {
            return Err(GitError::ForeignWorktree {
                worktree: dir.to_path_buf(),
                common_dir: common_dir.to_path_buf(),
            });
        }
        is_dirty(at).map(Some)
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
        let at = self.at();
        let out = text(at, &args, git(at, &args)?)?;
        let unreadable = || GitError::Unreadable {
            command: command_line(at, &args),
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

/// Whether a worktree has changes, untracked files included. The call
/// names a git directory (or the `.git` file a linked worktree has) and the
/// work tree, and never discovers: a worktree whose `.git` is gone is an
/// error, never a read of the repository above it.
fn is_dirty(at: At<'_>) -> Result<bool, GitError> {
    let args = [
        "status",
        "--porcelain",
        "-z",
        "--untracked-files=normal",
        "--ignore-submodules=none",
    ];
    Ok(!git(at, &args)?.is_empty())
}

fn command_line(at: At<'_>, args: &[&str]) -> String {
    let target = match at {
        At::Discover(dir) => format!("-C {}", dir.display()),
        At::Recorded { git_dir, work_tree } => format!(
            "--git-dir {} --work-tree {}",
            git_dir.display(),
            work_tree.display()
        ),
    };
    format!("git {target} {}", args.join(" "))
}

fn text(at: At<'_>, args: &[&str], bytes: Vec<u8>) -> Result<String, GitError> {
    String::from_utf8(bytes).map_err(|_| GitError::Unreadable {
        command: command_line(at, args),
        why: "the output is not UTF-8".to_owned(),
    })
}

/// Whether an inherited variable is git's (`GIT_DIR`, `GIT_CONFIG_*`,
/// `GIT_CEILING_DIRECTORIES`, `GIT_NO_REPLACE_OBJECTS` and every other).
fn is_git_variable(name: &OsStr) -> bool {
    name.as_encoded_bytes().starts_with(b"GIT_")
}

/// The command for one call: no shell, no prompt, a fixed locale, and no
/// inherited `GIT_*` variable, so neither a hook's environment nor a
/// caller's `GIT_CONFIG_*` chooses the repository or its configuration.
fn command(at: At<'_>, args: &[&str], inherited: impl IntoIterator<Item = OsString>) -> Command {
    let mut command = Command::new("git");
    for name in inherited {
        if is_git_variable(&name) {
            command.env_remove(name);
        }
    }
    match at {
        At::Discover(dir) => {
            command.arg("-C").arg(dir);
        }
        At::Recorded { git_dir, work_tree } => {
            command
                .arg("--git-dir")
                .arg(git_dir)
                .arg("--work-tree")
                .arg(work_tree);
        }
    }
    command
        .args(READ_ONLY_OPTIONS)
        .args(args)
        .stdin(Stdio::null())
        .env("LC_ALL", "C")
        .env("GIT_TERMINAL_PROMPT", "0");
    command
}

/// Runs one call and returns its standard output.
fn git(at: At<'_>, args: &[&str]) -> Result<Vec<u8>, GitError> {
    let inherited = std::env::vars_os().map(|(name, _)| name);
    let output = command(at, args, inherited)
        .output()
        .map_err(|error| GitError::Spawn {
            command: command_line(at, args),
            message: error.to_string(),
        })?;
    if output.status.success() {
        Ok(output.stdout)
    } else {
        Err(GitError::Failed {
            command: command_line(at, args),
            status: output.status.code(),
            stderr: String::from_utf8_lossy(&output.stderr).trim().to_owned(),
        })
    }
}

#[cfg(test)]
mod tests {
    use std::ffi::{OsStr, OsString};
    use std::path::Path;

    use super::{At, Checkout, Record, command, parse_worktrees};

    #[test]
    fn every_inherited_git_variable_is_removed() {
        let inherited = [
            "GIT_DIR",
            "GIT_CONFIG_PARAMETERS",
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_KEY_0",
            "GIT_CONFIG_VALUE_0",
            "GIT_NO_REPLACE_OBJECTS",
            "GIT_CEILING_DIRECTORIES",
            "GIT_TERMINAL_PROMPT",
            "PATH",
            "HOME",
        ];
        let built = command(
            At::Discover(Path::new("/r")),
            &["status"],
            inherited.iter().map(OsString::from),
        );
        let envs: Vec<(&OsStr, Option<&OsStr>)> = built.get_envs().collect();
        for name in &inherited[..7] {
            assert!(
                envs.contains(&(OsStr::new(name), None)),
                "{name} is not removed"
            );
        }
        assert!(envs.contains(&(OsStr::new("GIT_TERMINAL_PROMPT"), Some(OsStr::new("0")))));
        assert!(envs.contains(&(OsStr::new("LC_ALL"), Some(OsStr::new("C")))));
        assert!(
            !envs
                .iter()
                .any(|(name, _)| *name == "PATH" || *name == "HOME")
        );
    }

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
