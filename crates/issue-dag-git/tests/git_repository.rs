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

#[test]
fn a_nested_repository_whose_git_dir_is_removed_never_reads_the_outer_one() {
    let scratch = Scratch::new("nested");
    let (outer, _) = fixture(&scratch);
    let inner = outer.join("inner");
    fs::create_dir(&inner).expect("create the inner repository");
    git(&inner, &["init", "-q"]);
    fs::write(inner.join("i.txt"), "i\n").expect("write");
    git(&inner, &["add", "i.txt"]);
    git(&inner, &["commit", "-q", "-m", "inner"]);
    let local = GitRepository::open(&inner).expect("the inner repository");
    assert_eq!(value(local.branch_names()), vec!["main".to_owned()]);

    fs::remove_dir_all(inner.join(".git")).expect("remove the inner .git");
    // The outer repository has `main`, FEATURE and a worktree; none of it
    // may be answered for the inner one.
    assert!(matches!(local.branch_names(), Observed::Unavailable(_)));
    assert!(matches!(local.branches(), Observed::Unavailable(_)));
    assert!(matches!(local.worktrees(), Observed::Unavailable(_)));
    assert!(matches!(
        local.ahead_behind(FEATURE, "main"),
        Observed::Unavailable(_)
    ));
}

#[test]
fn a_subdirectory_or_git_dir_of_a_repository_is_refused() {
    let scratch = Scratch::new("subdir");
    let (repo, _) = fixture(&scratch);
    let sub = repo.join("plain subdirectory");
    fs::create_dir(&sub).expect("create a subdirectory");
    match GitRepository::open(&sub) {
        Err(GitError::NotTopLevel { path, top_level }) => {
            assert_eq!(path, sub);
            assert_eq!(top_level, repo);
        }
        other => panic!("expected NotTopLevel, got {other:?}"),
    }
    assert!(GitRepository::open(repo.join(".git")).is_err());
}

#[test]
fn a_linked_worktree_opens_at_its_top_level() {
    let scratch = Scratch::new("linked");
    let (_, extra) = fixture(&scratch);
    let local = GitRepository::open(&extra).expect("the linked worktree");
    assert_eq!(local.path(), extra.as_path());
    assert_eq!(value(local.worktrees()).len(), 2);
}

#[test]
fn a_revision_that_looks_like_an_option_writes_nothing() {
    let scratch = Scratch::new("inject");
    let (repo, _) = fixture(&scratch);
    let local = GitRepository::open(&repo).expect("a repository");
    let target = scratch.path().join("x");
    let revision = format!("--output={}", path_of(&target));
    let before = entries(scratch.path());
    assert!(matches!(
        local.ahead_behind(&revision, "main"),
        Observed::Unavailable(_)
    ));
    assert!(!target.exists());
    // Read as an option, git would write `<target>...main`.
    assert!(!scratch.path().join("x...main").exists());
    assert_eq!(entries(scratch.path()), before);
}

fn entries(dir: &Path) -> Vec<PathBuf> {
    let mut names: Vec<PathBuf> = fs::read_dir(dir)
        .expect("list a directory")
        .map(|entry| entry.expect("an entry").path())
        .collect();
    names.sort();
    names
}

#[test]
fn reads_never_write_the_index() {
    let scratch = Scratch::new("readonly");
    let (repo, extra) = fixture(&scratch);
    // A changed mtime makes a refreshing status rewrite the index.
    let past = std::time::SystemTime::UNIX_EPOCH + std::time::Duration::from_hours(438_288);
    for tracked in [repo.join("a.txt"), extra.join("b.txt")] {
        fs::File::options()
            .write(true)
            .open(&tracked)
            .expect("open a tracked file")
            .set_modified(past)
            .expect("touch a tracked file");
    }
    let index = repo.join(".git").join("index");
    let snapshot = || {
        (
            fs::read(&index).expect("read the index"),
            fs::metadata(&index)
                .expect("stat the index")
                .modified()
                .expect("the index mtime"),
        )
    };
    let before = snapshot();
    // Let a rewrite show in the mtime even on a coarse clock.
    std::thread::sleep(std::time::Duration::from_millis(1100));
    let local = GitRepository::open(&repo).expect("a repository");
    let _ = value(local.branch_names());
    let _ = value(local.branches());
    let _ = value(local.worktrees());
    let _ = value(local.ahead_behind(FEATURE, "main"));
    assert_eq!(snapshot(), before);
}

#[cfg(unix)]
#[test]
fn a_configured_fsmonitor_is_never_run() {
    use std::os::unix::fs::PermissionsExt;

    let scratch = Scratch::new("fsmonitor");
    let (repo, _) = fixture(&scratch);
    let marker = scratch.path().join("fsmonitor ran");
    let hook = scratch.path().join("fsmonitor-hook");
    fs::write(&hook, format!("#!/bin/sh\ntouch '{}'\n", path_of(&marker))).expect("write the hook");
    fs::set_permissions(&hook, fs::Permissions::from_mode(0o755)).expect("make it executable");
    git(&repo, &["config", "core.fsmonitor", &path_of(&hook)]);
    git(&repo, &["config", "core.untrackedCache", "true"]);
    let local = GitRepository::open(&repo).expect("a repository");
    let _ = value(local.worktrees());
    assert!(!marker.exists(), "status ran the configured fsmonitor");
}
