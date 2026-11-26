//! The values the [`LocalRepository`](crate::LocalRepository) port answers
//! with: branches, worktrees and the divergence of two revisions. They are
//! what the inventory reports (`inventory.branch`, `inventory.worktree`).

/// Where a branch lives.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BranchScope {
    /// A local branch, `refs/heads/<name>`.
    Local,
    /// A remote-tracking branch, `refs/remotes/<remote>/<name>`.
    Remote,
}

/// One branch and its tip.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Branch {
    /// Local or remote-tracking.
    pub scope: BranchScope,
    /// The name without its `refs/heads/` or `refs/remotes/` prefix; a
    /// remote-tracking branch keeps its remote, as in `origin/main`.
    pub name: String,
    /// The full object name of the tip commit.
    pub head: String,
    /// The subject line of the tip commit.
    pub tip_subject: String,
}

/// One worktree of the repository, the main one included.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Worktree {
    /// The worktree's directory, as git records it.
    pub path: String,
    /// Whether that directory exists.
    pub path_exists: bool,
    /// The full object name of its `HEAD`; `None` for a bare repository.
    pub head: Option<String>,
    /// What is checked out.
    pub checkout: Checkout,
    /// Whether the worktree is locked.
    pub locked: bool,
    /// Whether git considers the worktree prunable (its directory or its
    /// administrative files are gone).
    pub prunable: bool,
    /// Whether it has uncommitted changes, untracked files included; `None`
    /// when there is no directory or no working tree to inspect, or its work
    /// tree is not known.
    pub dirty: Option<bool>,
}

/// What a worktree has checked out.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Checkout {
    /// A branch, named without `refs/heads/`.
    Branch(String),
    /// A detached `HEAD`.
    Detached,
    /// Nothing: the bare main repository.
    Bare,
}

/// How far a revision has diverged from a base: the commits only it has,
/// and the commits only the base has.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct AheadBehind {
    /// Commits reachable from the revision and not from the base.
    pub ahead: u64,
    /// Commits reachable from the base and not from the revision.
    pub behind: u64,
}
