//! Why a read through `gh` failed, and the scrubbing of what `gh` said.

use core::fmt;
use std::ffi::OsString;

/// A read through `gh` that failed (fail closed): never an empty answer.
///
/// The forge answers the slot of a failed read as unavailable, with this
/// error's text as the reason, so a planning run that needs the slot is
/// incomplete (profile rule F1); the error itself is kept for the run's
/// report ([`crate::GhForge::failures`]). The command line exits with
/// [`GhError::EXIT_STATUS`] after any of them.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum GhError {
    /// `gh` could not be run, or exited with a failure that is not the
    /// HTTP 404 a lookup reads as "none": `gh.command_failed`.
    CommandFailed {
        /// The request, such as `gh api repos/o/r/issues/1`.
        source: String,
        /// What `gh` said, scrubbed of secrets and the home directory.
        detail: String,
    },
    /// `gh` answered, but not in the shape the read expects:
    /// `gh.response_invalid`.
    ResponseInvalid {
        /// The request.
        source: String,
        /// What is wrong with the answer.
        detail: String,
    },
    /// A list filled its limit, so it may have been truncated (threat model
    /// C15, profile rule I5): `gh.list_limit_reached`.
    ListLimitReached {
        /// The request.
        source: String,
        /// The limit it filled.
        limit: usize,
    },
}

impl GhError {
    /// The exit status of a run that a failed read made incomplete: 2, as
    /// for any incomplete run (profile rule F1, the Python compiler's
    /// "typed error (exit 2)").
    pub const EXIT_STATUS: u8 = 2;

    /// The stable code of the error, the Python compiler's code for the
    /// same failure.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::CommandFailed { .. } => "gh.command_failed",
            Self::ResponseInvalid { .. } => "gh.response_invalid",
            Self::ListLimitReached { .. } => "gh.list_limit_reached",
        }
    }

    pub(crate) fn invalid(source: &str, detail: impl Into<String>) -> Self {
        Self::ResponseInvalid {
            source: source.to_owned(),
            detail: detail.into(),
        }
    }
}

impl fmt::Display for GhError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::CommandFailed { source, detail } | Self::ResponseInvalid { source, detail } => {
                write!(f, "{source}: {detail}")
            }
            Self::ListLimitReached { source, limit } => write!(
                f,
                "{source}: the result filled --limit {limit}; possible truncation"
            ),
        }
    }
}

impl std::error::Error for GhError {}

/// The token variables `gh help environment` names; their values never
/// reach a reason.
const TOKEN_VARIABLES: [&str; 4] = [
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
];

/// Query or fragment parameters whose value is redacted inside a URL.
const SECRET_PARAMETERS: [&str; 9] = [
    "access_token",
    "token",
    "key",
    "secret",
    "password",
    "signature",
    "sig",
    "auth",
    "code",
];

/// The longest reason kept, in characters.
const MAX_DETAIL: usize = 600;

/// The values of the token variables, as `gh` will see them.
pub fn secrets(env: &[(OsString, OsString)]) -> Vec<String> {
    TOKEN_VARIABLES
        .iter()
        .flat_map(|name| {
            let given = env
                .iter()
                .rev()
                .find(|(key, _)| key == name)
                .map(|(_, value)| value.clone());
            [given, std::env::var_os(name)]
        })
        .flatten()
        .filter_map(|value| value.into_string().ok())
        .filter(|value| !value.is_empty())
        .collect()
}

/// What `gh` said, made safe to report: no token value, no credential or
/// secret parameter inside a URL, no home directory, one line, bounded.
pub fn scrub(text: &str, secrets: &[String]) -> String {
    let mut text = text.to_owned();
    for secret in secrets {
        text = text.replace(secret.as_str(), "[redacted]");
    }
    let mut text = text
        .split_whitespace()
        .map(scrub_word)
        .collect::<Vec<_>>()
        .join(" ");
    if let Some(home) = std::env::var_os("HOME").and_then(|h| h.into_string().ok())
        && !home.is_empty()
        && home != "/"
    {
        text = text.replace(home.as_str(), "~");
    }
    if text.chars().count() > MAX_DETAIL {
        text = text.chars().take(MAX_DETAIL - 3).collect::<String>() + "...";
    }
    text
}

/// A word that holds a URL loses the credential in its authority and the
/// value of every secret parameter.
fn scrub_word(word: &str) -> String {
    let Some(at) = word.find("://") else {
        return word.to_owned();
    };
    let (scheme, rest) = word.split_at(at + 3);
    let authority_end = rest.find('/').unwrap_or(rest.len());
    let rest = rest[..authority_end].rfind('@').map_or_else(
        || rest.to_owned(),
        |credential| format!("[redacted]{}", &rest[credential..]),
    );
    let mut out = String::from(scheme);
    let mut chars = rest.char_indices().peekable();
    let mut start = 0;
    while let Some((i, c)) = chars.next() {
        if !matches!(c, '?' | '&' | ';' | '#') {
            continue;
        }
        // Compared as bytes: a parameter name is ASCII, and the text after
        // the separator need not end on a character boundary at its length.
        let tail = &rest.as_bytes()[i + 1..];
        let Some(name) = SECRET_PARAMETERS.iter().find(|name| {
            tail.len() > name.len()
                && tail[..name.len()].eq_ignore_ascii_case(name.as_bytes())
                && tail[name.len()] == b'='
        }) else {
            continue;
        };
        let value_start = i + 1 + name.len() + 1;
        let value_end = rest[value_start..]
            .find(['&', '#'])
            .map_or(rest.len(), |end| value_start + end);
        out.push_str(&rest[start..value_start]);
        out.push_str("[redacted]");
        start = value_end;
        while chars.peek().is_some_and(|(j, _)| *j < value_end) {
            chars.next();
        }
    }
    out.push_str(&rest[start..]);
    out
}

#[cfg(test)]
mod tests {
    use super::scrub;

    #[test]
    fn a_url_with_non_ascii_query_text_is_scrubbed_without_a_panic() {
        assert_eq!(
            scrub("HTTP 500 at https://host/path?ééééé&token=abc", &[]),
            "HTTP 500 at https://host/path?ééééé&token=[redacted]"
        );
        assert_eq!(scrub("https://h/?é", &[]), "https://h/?é");
    }

    #[test]
    fn a_url_loses_its_credential_and_its_secret_parameters() {
        assert_eq!(
            scrub(
                "at https://user:pw@host/x?a=1&Token=abc&b=2#sig=zz now",
                &[]
            ),
            "at https://[redacted]@host/x?a=1&Token=[redacted]&b=2#sig=[redacted] now"
        );
    }

    #[test]
    fn a_token_value_is_redacted_and_the_text_is_one_line() {
        assert_eq!(
            scrub("bad\n token  t0k3n\n", &["t0k3n".to_owned()]),
            "bad token [redacted]"
        );
    }

    #[test]
    fn a_long_reason_is_cut() {
        let text = "x ".repeat(1000);
        assert_eq!(scrub(&text, &[]).chars().count(), 600);
    }
}
