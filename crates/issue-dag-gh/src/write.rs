//! The forge write port through `gh` (flyingrobots/taskalisk#1): the
//! account a write is made as (`gh api user`) and the one write an edge edit
//! makes, the replacement of an issue body (`gh api -X PATCH`).

use core::fmt;

use issue_dag_core::{Actor, ForgeWrite, IssueRef, Observed};
use serde_json::{Value, json};

use crate::GhForge;
use crate::error::GhError;
use crate::run::Refusal;

const WRITER_SOURCE: &str = "gh api user";

/// A write through `gh` that failed: `gh.mutation_failed`.
///
/// The request may have been applied before the failure, so whether the body changed is
/// unknown; it is reported, never retried or undone (edge-edit rule E9).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WriteFailure {
    /// The request, such as `gh api -X PATCH repos/o/r/issues/1`.
    pub source: String,
    /// What `gh` said, scrubbed of secrets and the home directory.
    pub detail: String,
}

impl WriteFailure {
    /// The stable code of the failure.
    pub const CODE: &'static str = "gh.mutation_failed";
}

impl fmt::Display for WriteFailure {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.source, self.detail)
    }
}

impl std::error::Error for WriteFailure {}

impl ForgeWrite for GhForge {
    type Error = WriteFailure;

    /// `gh api user`: the account of the token `gh` writes with. A token
    /// that cannot read it, such as an app installation token, leaves the
    /// writer unavailable, and the failure is kept ([`GhForge::failures`]).
    fn writer(&self) -> Observed<Actor> {
        let read = self
            .runner
            .run_strict(WRITER_SOURCE, &["api".to_owned(), "user".to_owned()])
            .and_then(|out| {
                let value: Value = serde_json::from_slice(&out).map_err(|error| {
                    GhError::invalid(WRITER_SOURCE, format!("unparseable JSON output: {error}"))
                })?;
                let login = value["login"]
                    .as_str()
                    .filter(|login| !login.trim().is_empty())
                    .ok_or_else(|| GhError::invalid(WRITER_SOURCE, "the account has no login"))?;
                let actor_type = match &value["type"] {
                    Value::Null => "User",
                    Value::String(kind) => kind,
                    _ => return Err(GhError::invalid(WRITER_SOURCE, "type is not a string")),
                };
                Ok(Actor {
                    login: login.to_owned(),
                    actor_type: actor_type.to_owned(),
                })
            });
        self.settle(read)
    }

    /// One `gh api -X PATCH repos/<owner>/<repo>/issues/<n> --input -`, the
    /// JSON `{"body": ...}` on its standard input, so the body is never an
    /// argument. Made once: a failure is returned, never retried.
    fn replace_body(&self, issue: &IssueRef, body: &str) -> Result<(), WriteFailure> {
        let path = format!(
            "repos/{}/{}/issues/{}",
            issue.owner(),
            issue.repo(),
            issue.number()
        );
        let source = format!("gh api -X PATCH {path}");
        let argv: Vec<String> = ["api", "-X", "PATCH", &path, "--input", "-"]
            .iter()
            .map(|a| (*a).to_owned())
            .collect();
        let input = json!({ "body": body }).to_string();
        match self.runner.run_with(&source, &argv, Some(input.as_bytes())) {
            Ok(_) => Ok(()),
            Err(Refusal::NotFound) => Err(WriteFailure {
                source,
                detail: "Not Found (HTTP 404)".to_owned(),
            }),
            Err(Refusal::Failed(error)) => Err(WriteFailure {
                source,
                detail: match error {
                    GhError::CommandFailed { detail, .. }
                    | GhError::ResponseInvalid { detail, .. } => detail.trim().to_owned(),
                    GhError::ListLimitReached { .. } => error.to_string(),
                },
            }),
        }
    }
}
