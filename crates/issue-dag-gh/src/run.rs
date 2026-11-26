//! Running `gh`: an argument vector, never a shell string.

use std::ffi::OsString;
use std::process::{Command, Stdio};

use crate::error::{GhError, scrub, secrets};

/// Variables removed from `gh`'s environment, inherited or given: each makes
/// `gh` write for a terminal, in colour, or with debug output, none of which
/// a reader of its output expects.
const UNSET: [&str; 4] = ["GH_FORCE_TTY", "CLICOLOR_FORCE", "GH_DEBUG", "DEBUG"];

/// Variables `gh` always runs with: no prompt, no colour, no update notice,
/// no pager.
const FORCED: [(&str, &str); 4] = [
    ("GH_PROMPT_DISABLED", "1"),
    ("NO_COLOR", "1"),
    ("GH_NO_UPDATE_NOTIFIER", "1"),
    ("GH_PAGER", "cat"),
];

/// How `gh` is run: the program and the environment it is given on top of
/// this process's. The variables of [`UNSET`] and [`FORCED`] are applied
/// after `env`, so the caller cannot turn them off.
#[derive(Clone, Debug)]
pub struct Runner {
    pub program: OsString,
    pub env: Vec<(OsString, OsString)>,
}

/// A `gh` run that did not succeed.
pub enum Refusal {
    /// `gh` reported HTTP 404, the one failure a lookup may read as "none"
    /// (the Python compiler's `"HTTP 404" in err`).
    NotFound,
    /// Any other failure.
    Failed(GhError),
}

impl Runner {
    /// Runs `gh` with `argv` and returns its standard output.
    pub fn run(&self, source: &str, argv: &[String]) -> Result<Vec<u8>, Refusal> {
        let secrets = secrets(&self.env);
        let failed = |detail: String| {
            Refusal::Failed(GhError::CommandFailed {
                source: source.to_owned(),
                detail: scrub(&detail, &secrets),
            })
        };
        let mut command = Command::new(&self.program);
        command
            .args(argv)
            .envs(self.env.iter().map(|(k, v)| (k, v)));
        // After the caller's variables, so that none of them turns this off.
        for name in UNSET {
            command.env_remove(name);
        }
        command.envs(FORCED).stdin(Stdio::null());
        let output = command.output().map_err(|error| {
            failed(format!(
                "{} could not be run: {error}",
                self.program.to_string_lossy()
            ))
        })?;
        if output.status.success() {
            return Ok(output.stdout);
        }
        let stderr = String::from_utf8_lossy(&output.stderr);
        if stderr.contains("HTTP 404") {
            return Err(Refusal::NotFound);
        }
        Err(failed(if stderr.trim().is_empty() {
            format!("command failed ({})", output.status)
        } else {
            stderr.into_owned()
        }))
    }

    /// Runs `gh`; HTTP 404 is a failure like any other.
    pub fn run_strict(&self, source: &str, argv: &[String]) -> Result<Vec<u8>, GhError> {
        self.run(source, argv).map_err(|refusal| match refusal {
            Refusal::Failed(error) => error,
            Refusal::NotFound => GhError::CommandFailed {
                source: source.to_owned(),
                detail: "Not Found (HTTP 404)".to_owned(),
            },
        })
    }
}
