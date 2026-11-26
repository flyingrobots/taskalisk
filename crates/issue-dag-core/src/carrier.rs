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
    let Some(lines) = block_lines(body) else {
        return Parse::NoDocument;
    };
    if lines
        .iter()
        .any(|line| has_forbidden_break(&body[line.clone()]))
    {
        return Parse::Unreadable;
    }
    let mut entries = Vec::new();
    let mut violations = BTreeSet::new();
    let mut keys = BTreeSet::new();
    for line in lines {
        let text = &body[line.clone()];
        let content = text.trim_end_matches([' ', '\t']);
        if content.is_empty() || content.trim_start_matches([' ', '\t']).starts_with('#') {
            continue; // C5
        }
        let Some((key, raw)) = split_entry(content) else {
            violations.insert(Label::C6);
            continue;
        };
        if !keys.insert(key) {
            violations.insert(Label::C7);
        }
        let value = read_value(trim(raw));
        if value.is_none() {
            violations.insert(Label::C8);
        }
        entries.push(Entry {
            key: key.to_owned(),
            value,
            line,
        });
    }
    Parse::Block(Block {
        entries,
        violations,
    })
}

/// The byte ranges, without line ends, of the block's content lines (rules
/// C1 and C2), or `None` when the body has no block (rule C3).
pub fn block_lines(body: &str) -> Option<Vec<Range<usize>>> {
    let mut pos = opening_fence_end(body)?;
    let mut lines = Vec::new();
    loop {
        let rest = &body[pos..];
        let (segment_end, next) = rest
            .find('\n')
            .map_or((body.len(), None), |i| (pos + i, Some(pos + i + 1)));
        // A CR directly before an LF belongs to the line end.
        let line_end = if next.is_some() && body[pos..segment_end].ends_with('\r') {
            segment_end - 1
        } else {
            segment_end
        };
        if !lines.is_empty() && is_closing_fence(&body[pos..line_end]) {
            return Some(lines);
        }
        let next = next?; // the body ended before a closing fence
        lines.push(pos..line_end);
        pos = next;
    }
}

/// C1: the byte offset just after the opening fence's line end.
fn opening_fence_end(body: &str) -> Option<usize> {
    let rest = body.trim_start_matches([' ', '\t', '\r', '\n']);
    let rest = rest.strip_prefix("```yaml")?;
    let rest = rest.trim_start_matches([' ', '\t']);
    let rest = rest
        .strip_prefix("\r\n")
        .or_else(|| rest.strip_prefix('\n'))?;
    Some(body.len() - rest.len())
}

/// C2: three backticks and zero or more blanks.
fn is_closing_fence(line: &str) -> bool {
    line.strip_prefix("```")
        .is_some_and(|rest| rest.bytes().all(|b| b == b' ' || b == b'\t'))
}

/// C4: a lone CR, or a character that some readers take as a line break.
fn has_forbidden_break(line: &str) -> bool {
    line.chars().any(|c| {
        matches!(
            c,
            '\r' | '\u{000B}'
                | '\u{000C}'
                | '\u{001C}'
                | '\u{001D}'
                | '\u{001E}'
                | '\u{0085}'
                | '\u{2028}'
                | '\u{2029}'
        )
    })
}

/// C6: `key *blank ":" *blank value`, the key in the first column. Returns
/// the key and the untrimmed value.
fn split_entry(line: &str) -> Option<(&str, &str)> {
    let bytes = line.as_bytes();
    let start = usize::from(bytes.first() == Some(&b'.'));
    let first = *bytes.get(start)?;
    if !(first.is_ascii_alphabetic() || first == b'_') {
        return None;
    }
    let key_len = start
        + 1
        + bytes[start + 1..]
            .iter()
            .take_while(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'-'))
            .count();
    let (key, rest) = line.split_at(key_len);
    let rest = rest.trim_start_matches([' ', '\t']).strip_prefix(':')?;
    Some((key, rest))
}

/// C8 to C10: reads a trimmed value. `None` for a list without its `]`.
fn read_value(text: &str) -> Option<Value> {
    if let Some(after) = text.strip_prefix('[') {
        let inner = after.strip_suffix(']')?;
        if trim(inner).is_empty() {
            return Some(Value::List(Vec::new()));
        }
        let items = inner
            .split(',')
            .map(|part| unquote(trim(part)).to_owned())
            .collect();
        return Some(Value::List(items));
    }
    let unquoted = unquote(text);
    if unquoted.len() == text.len()
        && let Some(integer) = Integer::parse(text)
    {
        return Some(Value::Integer(integer));
    }
    Some(Value::String(unquoted.to_owned()))
}

/// C9: a text of two or more characters that begins and ends with the same
/// quote character loses both; there are no escapes.
fn unquote(text: &str) -> &str {
    for quote in ['"', '\''] {
        if text.chars().count() >= 2
            && let Some(inner) = text.strip_prefix(quote).and_then(|t| t.strip_suffix(quote))
        {
            return inner;
        }
    }
    text
}

/// Removes every leading and trailing blank (SP or HT).
#[must_use]
pub fn trim(text: &str) -> &str {
    text.trim_matches([' ', '\t'])
}
