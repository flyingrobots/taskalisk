//! The decoded record of a valid document (format rule M4).

use std::collections::BTreeSet;

use crate::reference::IssueRef;

/// The version every record of this format carries.
pub const VERSION: &str = "issue-dag/2";

/// `.kind` (rule V4).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Kind {
    /// `task`
    Task,
    /// `container`
    Container,
}

impl Kind {
    pub(crate) fn from_str(text: &str) -> Option<Self> {
        match text {
            "task" => Some(Self::Task),
            "container" => Some(Self::Container),
            _ => None,
        }
    }

    /// The value as written.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Task => "task",
            Self::Container => "container",
        }
    }
}

/// `.type` (rule V5).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum TaskType {
    /// `feature`
    Feature,
    /// `bug`
    Bug,
    /// `decision`
    Decision,
    /// `research`
    Research,
    /// `investigation`
    Investigation,
    /// `spike`
    Spike,
    /// `task`
    Task,
}

impl TaskType {
    pub(crate) fn from_str(text: &str) -> Option<Self> {
        match text {
            "feature" => Some(Self::Feature),
            "bug" => Some(Self::Bug),
            "decision" => Some(Self::Decision),
            "research" => Some(Self::Research),
            "investigation" => Some(Self::Investigation),
            "spike" => Some(Self::Spike),
            "task" => Some(Self::Task),
            _ => None,
        }
    }

    /// The value as written.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Feature => "feature",
            Self::Bug => "bug",
            Self::Decision => "decision",
            Self::Research => "research",
            Self::Investigation => "investigation",
            Self::Spike => "spike",
            Self::Task => "task",
        }
    }
}

/// `.status` (rule V8).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Status {
    /// `active`
    Active,
    /// `parked`
    Parked,
    /// `blocked`
    Blocked,
}

impl Status {
    pub(crate) fn from_str(text: &str) -> Option<Self> {
        match text {
            "active" => Some(Self::Active),
            "parked" => Some(Self::Parked),
            "blocked" => Some(Self::Blocked),
            _ => None,
        }
    }

    /// The value as written.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Parked => "parked",
            Self::Blocked => "blocked",
        }
    }
}

/// A meter claim `name` or `name*N` (rule L3).
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct MeterClaim {
    /// The meter's name.
    pub name: String,
    /// The slots claimed; 1 when the claim has no `*N`.
    pub slots: u32,
}

impl MeterClaim {
    /// Reads a meter claim, or `None` when the text is not one.
    #[must_use]
    pub fn parse(text: &str) -> Option<Self> {
        let (name, slots) = match text.split_once('*') {
            Some((name, n)) => (name, crate::reference::parse_number(n)?),
            None => (text, 1),
        };
        let name_ok = !name.is_empty()
            && name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'/' | b'-'));
        name_ok.then(|| Self {
            name: name.to_owned(),
            slots,
        })
    }
}

/// The record a valid document decodes to (rule M4). Its version is always
/// [`VERSION`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Record {
    /// `.id`, in canonical form.
    pub id: IssueRef,
    /// `.kind`.
    pub kind: Kind,
    /// `.type`, or none when absent.
    pub task_type: Option<TaskType>,
    /// For a task, its prerequisites in written order, duplicates kept; none for a container.
    pub blocked_by: Option<Vec<IssueRef>>,
    /// For a container, its children in written order, duplicates kept; none for a task.
    pub children: Option<Vec<IssueRef>>,
    /// `.size_hours`, or none when absent.
    pub size_hours: Option<u32>,
    /// The set of `.holds` keys; empty when absent.
    pub holds: BTreeSet<String>,
    /// The `.meters` claims in written order; empty when absent.
    pub meters: Vec<MeterClaim>,
    /// `.status`, or none when absent.
    pub status: Option<Status>,
}

impl Record {
    /// The record's version, `issue-dag/2`.
    #[must_use]
    pub const fn version(&self) -> &'static str {
        VERSION
    }
}
