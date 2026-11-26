//! The carrier (format rules C1 to C10): locates the frontmatter block in a
//! body and reads its entry lines.

use std::collections::BTreeSet;
use std::ops::Range;

use crate::label::Label;

/// A value of an entry line (rules C8 to C10).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Value {
    /// A list; every item is a string (C8).
    List(Vec<String>),
    /// A scalar that is not an integer, unquoted (C8, C9).
    String(String),
    /// An unquoted scalar of an optional `-` and one or more ASCII digits (C8).
    Integer(Integer),
}

/// An integer as written: its sign and its decimal digits. It may spell a
/// number too large for any machine type, so its value is read on demand.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Integer {
    negative: bool,
    /// The digits without leading zeros; empty for zero.
    digits: String,
}

impl Integer {
    fn parse(text: &str) -> Option<Self> {
        let (negative, digits) = text
            .strip_prefix('-')
            .map_or((false, text), |rest| (true, rest));
        if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }
        Some(Self {
            negative,
            digits: digits.trim_start_matches('0').to_owned(),
        })
    }

    /// The value, or `None` when it does not fit in an `i64`.
    #[must_use]
    pub fn to_i64(&self) -> Option<i64> {
        if self.digits.is_empty() {
            return Some(0);
        }
        let text = if self.negative {
            format!("-{}", self.digits)
        } else {
            self.digits.clone()
        };
        text.parse().ok()
    }
}

/// One entry line of a block (rule C6).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Entry {
    /// The key, with its `.` prefix when it is a format key.
    pub key: String,
    /// The value; `None` for a list that does not end with `]` (rule C8).
    pub value: Option<Value>,
    /// The byte range of the line in the body, without its line end.
    pub line: Range<usize>,
}

/// A frontmatter block: its entry lines in written order, and the violations
/// of rules C6 to C8 its lines have.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Block {
    entries: Vec<Entry>,
    violations: BTreeSet<Label>,
}

impl Block {
    /// The entry lines, in written order.
    #[must_use]
    pub fn entries(&self) -> &[Entry] {
        &self.entries
    }

    /// The carrier violations (C6, C7, C8) of the block's lines.
    #[must_use]
    pub const fn violations(&self) -> &BTreeSet<Label> {
        &self.violations
    }

    /// The value of a key for the rules of sections 3 to 5: the value of the
    /// first entry line with that key that gives it one (rule C8), or `None`
    /// when the key is absent.
    #[must_use]
    pub fn value(&self, key: &str) -> Option<&Value> {
        self.entries
            .iter()
            .filter(|e| e.key == key)
            .find_map(|e| e.value.as_ref())
    }
}

/// What the carrier finds in a body.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Parse {
    /// The body has no frontmatter block (rule C3); it is not a document.
    NoDocument,
    /// The block has a line break rule C4 forbids. Its lines cannot be told
    /// apart, so C4 is its only violation.
    Unreadable,
    /// The block, read into entry lines.
    Block(Block),
}

/// Locates and reads the frontmatter block of a body.
#[must_use]
pub fn parse(body: &str) -> Parse {
    let _ = body;
    Parse::NoDocument
}

/// Removes every leading and trailing blank (SP or HT).
#[must_use]
pub fn trim(text: &str) -> &str {
    text.trim_matches([' ', '\t'])
}
