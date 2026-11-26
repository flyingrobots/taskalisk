//! The git adapter over real temporary repositories.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};

use issue_dag_core::{AheadBehind, BranchScope, Checkout, LocalRepository, Observed, Worktree};
use issue_dag_git::{GitError, GitRepository};

const FEATURE: &str = "feature/naïve-ünïcode";

/// A directory that is removed when the test ends.
struct Scratch(PathBuf);

impl Scratch {
    fn new(label: &str) -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let n = NEXT.fetch_add(1, Ordering::Relaxed);
        let base =
            std::env::temp_dir().join(format!("issue-dag-git-{label}-{}-{n}", std::process::id()));
        if base.exists() {
            fs::remove_dir_all(&base).expect("clear a stale scratch directory");
        }
        fs::create_dir_all(&base).expect("create a scratch directory");
        // git records canonical paths (on macOS /var is /private/var).
        Self(base.canonicalize().expect("canonical scratch path"))
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

/// Runs git for the fixture, isolated from the caller's configuration and
/// from any repository named by the environment.
fn git(dir: &Path, args: &[&str]) -> String {
    let output = Command::new("git")
        .arg("-C")
        .arg(dir)
        .args([
            "-c",
            "init.defaultBranch=main",
            "-c",
            "commit.gpgsign=false",
        ])
        .args(args)
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_INDEX_FILE")
        .env_remove("GIT_COMMON_DIR")
        .env_remove("GIT_OBJECT_DIRECTORY")
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_AUTHOR_NAME", "Fixture")
        .env("GIT_AUTHOR_EMAIL", "fixture@example.invalid")
        .env("GIT_COMMITTER_NAME", "Fixture")
        .env("GIT_COMMITTER_EMAIL", "fixture@example.invalid")
        .output()
        .expect("run git");
    assert!(
        output.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout)
        .expect("utf-8")
        .trim()
        .to_owned()
}

/// A repository with `main` (one commit), `FEATURE` (one more), a
/// remote-tracking `origin/main` with `origin/HEAD` pointing at it, and the
/// returned extra worktree, whose path has spaces and non-ASCII letters,
/// checked out on `FEATURE`.
fn fixture(scratch: &Scratch) -> (PathBuf, PathBuf) {
    let repo = scratch.path().join("repo");
    fs::create_dir(&repo).expect("create repo dir");
    git(&repo, &["init", "-q"]);
    fs::write(repo.join("a.txt"), "a\n").expect("write");
    git(&repo, &["add", "a.txt"]);
    git(&repo, &["commit", "-q", "-m", "first"]);
    git(&repo, &["update-ref", "refs/remotes/origin/main", "HEAD"]);
    git(
        &repo,
        &[
            "symbolic-ref",
            "refs/remotes/origin/HEAD",
            "refs/remotes/origin/main",
        ],
    );
    let extra = scratch.path().join("extra worktree ✓");
    git(
        &repo,
        &[
            "worktree",
            "add",
            "-q",
            "-b",
            FEATURE,
            extra.to_str().expect("utf-8 path"),
        ],
    );
    fs::write(extra.join("b.txt"), "b\n").expect("write");
    git(&extra, &["add", "b.txt"]);
    git(&extra, &["commit", "-q", "-m", "second: café ✓"]);
    (repo, extra)
}

fn value<T: std::fmt::Debug>(observed: Observed<T>) -> T {
    match observed {
        Observed::Value(value) => value,
        Observed::Unavailable(why) => panic!("unavailable: {why}"),
    }
}

fn path_of(path: &Path) -> String {
    path.to_str().expect("utf-8 path").to_owned()
}

#[test]
fn reads_branches_worktrees_and_divergence() {
    let scratch = Scratch::new("read");
    let (repo, extra) = fixture(&scratch);
    let local = GitRepository::open(&repo).expect("a repository");

    assert_eq!(
        value(local.branch_names()),
        vec![FEATURE.to_owned(), "main".to_owned()]
    );

    let main_head = git(&repo, &["rev-parse", "main"]);
    let feature_head = git(&repo, &["rev-parse", FEATURE]);
    let branches = value(local.branches());
    let summary: Vec<_> = branches
        .iter()
        .map(|b| {
            (
                b.scope,
                b.name.as_str(),
                b.head.as_str(),
                b.tip_subject.as_str(),
            )
        })
        .collect();
    assert_eq!(
        summary,
        vec![
            (
                BranchScope::Local,
                FEATURE,
                feature_head.as_str(),
                "second: café ✓"
            ),
            (BranchScope::Local, "main", main_head.as_str(), "first"),
            (
                BranchScope::Remote,
                "origin/main",
                main_head.as_str(),
                "first"
            ),
        ]
    );

    assert_eq!(
        value(local.worktrees()),
        vec![
            Worktree {
                path: path_of(&repo),
                path_exists: true,
                head: Some(main_head),
                checkout: Checkout::Branch("main".to_owned()),
                locked: false,
                prunable: false,
                dirty: Some(false),
            },
            Worktree {
                path: path_of(&extra),
                path_exists: true,
                head: Some(feature_head),
                checkout: Checkout::Branch(FEATURE.to_owned()),
                locked: false,
                prunable: false,
                dirty: Some(false),
            },
        ]
    );

    assert_eq!(
        value(local.ahead_behind(FEATURE, "main")),
        AheadBehind {
            ahead: 1,
            behind: 0
        }
    );
    assert_eq!(
        value(local.ahead_behind("origin/main", FEATURE)),
        AheadBehind {
            ahead: 0,
            behind: 1
        }
    );
}

#[test]
fn an_untracked_file_makes_a_worktree_dirty() {
    let scratch = Scratch::new("dirty");
    let (repo, extra) = fixture(&scratch);
    fs::write(extra.join("new file ✓.txt"), "x\n").expect("write");
    let local = GitRepository::open(&repo).expect("a repository");
    let dirty: Vec<_> = value(local.worktrees())
        .into_iter()
        .map(|w| w.dirty)
        .collect();
    assert_eq!(dirty, vec![Some(false), Some(true)]);
}

#[test]
fn a_detached_locked_worktree() {
    let scratch = Scratch::new("locked");
    let (repo, _) = fixture(&scratch);
    let detached = scratch.path().join("detached");
    let detached_text = path_of(&detached);
    git(
        &repo,
        &["worktree", "add", "-q", "--detach", &detached_text, "main"],
    );
    git(
        &repo,
        &[
            "worktree",
            "lock",
            "--reason",
            "kept for a test",
            &detached_text,
        ],
    );
    let local = GitRepository::open(&repo).expect("a repository");
    let worktrees = value(local.worktrees());
    let found = worktrees
        .iter()
        .find(|w| w.path == detached_text)
        .expect("the detached worktree");
    assert_eq!(found.checkout, Checkout::Detached);
    assert!(found.locked);
    assert_eq!(found.dirty, Some(false));
}

#[test]
fn a_missing_worktree_directory_is_reported_not_dropped() {
    let scratch = Scratch::new("missing");
    let (repo, extra) = fixture(&scratch);
    fs::remove_dir_all(&extra).expect("remove the worktree directory");
    let local = GitRepository::open(&repo).expect("a repository");
    let worktrees = value(local.worktrees());
    assert_eq!(worktrees.len(), 2);
    let missing = &worktrees[1];
    assert_eq!(missing.path, path_of(&extra));
    assert!(!missing.path_exists);
    assert!(missing.prunable);
    assert_eq!(missing.dirty, None);
    assert_eq!(missing.checkout, Checkout::Branch(FEATURE.to_owned()));
}

#[test]
fn a_path_that_is_not_a_repository_fails() {
    let scratch = Scratch::new("plain");
    match GitRepository::open(scratch.path()) {
        Err(GitError::NotARepository { .. }) => {}
        other => panic!("expected NotARepository, got {other:?}"),
    }
    match GitRepository::open(scratch.path().join("absent")) {
        Err(GitError::NotARepository { .. }) => {}
        other => panic!("expected NotARepository, got {other:?}"),
    }
}

#[test]
fn a_repository_that_breaks_after_open_answers_unavailable_never_empty() {
    let scratch = Scratch::new("broken");
    let (repo, _) = fixture(&scratch);
    let local = GitRepository::open(&repo).expect("a repository");
    fs::remove_dir_all(repo.join(".git")).expect("break the repository");
    assert!(matches!(local.branch_names(), Observed::Unavailable(_)));
    assert!(matches!(local.branches(), Observed::Unavailable(_)));
    assert!(matches!(local.worktrees(), Observed::Unavailable(_)));
    assert!(local.read_worktrees().is_err());
}

#[test]
fn an_unknown_revision_is_unavailable() {
    let scratch = Scratch::new("unknown");
    let (repo, _) = fixture(&scratch);
    let local = GitRepository::open(&repo).expect("a repository");
    assert!(matches!(
        local.ahead_behind("main", "no-such-branch"),
        Observed::Unavailable(_)
    ));
    assert!(matches!(
        local.ahead_behind("--all", "main"),
        Observed::Unavailable(_)
    ));
}
