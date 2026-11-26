//! References (format rule L1).

use core::fmt;

/// The largest number a reference or a meter claim may carry (rules L1, L3).
pub const MAX_NUMBER: u32 = 2_147_483_647;

/// A reference `owner/repo#N` (rule L1), held in canonical form: owner and
/// repository in ASCII lower case. Two references are equal exactly when
/// rule L1 says they are.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct IssueRef {
    owner: String,
    repo: String,
    number: u32,
}

impl IssueRef {
    /// Reads a reference. The text is trimmed of blanks first (rule L1).
    /// Returns `None` when the text is not a reference.
    #[must_use]
    pub fn parse(text: &str) -> Option<Self> {
        let text = crate::carrier::trim(text);
        let (names, number) = text.split_once('#')?;
        let (owner, repo) = names.split_once('/')?;
        if !is_name(owner) || !is_name(repo) {
            return None;
        }
        Some(Self {
            owner: owner.to_ascii_lowercase(),
            repo: repo.to_ascii_lowercase(),
            number: parse_number(number)?,
        })
    }

    /// The owner, in ASCII lower case.
    #[must_use]
    pub fn owner(&self) -> &str {
        &self.owner
    }

    /// The repository name, in ASCII lower case.
    #[must_use]
    pub fn repo(&self) -> &str {
        &self.repo
    }

    /// The issue number, from 1 to [`MAX_NUMBER`].
    #[must_use]
    pub const fn number(&self) -> u32 {
        self.number
    }
}

impl fmt::Display for IssueRef {
    /// Writes the canonical form, `owner/repo#N`.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}/{}#{}", self.owner, self.repo, self.number)
    }
}

/// `name = 1*( ALPHA / DIGIT / "_" / "." / "-" )`.
fn is_name(text: &str) -> bool {
    !text.is_empty()
        && text
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-'))
}

/// `number = %x31-39 *DIGIT`, at most [`MAX_NUMBER`] (rule L1).
pub(crate) fn parse_number(text: &str) -> Option<u32> {
    let bytes = text.as_bytes();
    let first = *bytes.first()?;
    if !(b'1'..=b'9').contains(&first) || !bytes.iter().all(u8::is_ascii_digit) {
        return None;
    }
    // At most ten digits fit; parse in u64 so the bound check cannot overflow.
    if bytes.len() > 10 {
        return None;
    }
    let value: u64 = text.parse().ok()?;
    u32::try_from(value).ok().filter(|n| *n <= MAX_NUMBER)
}
