//! Capturing the observation bundle a live plan was made from, and planning
//! again from a bundle or an evaluation record with reads disabled
//! (flyingrobots/taskalisk#59).
//!
//! `plan --capture-bundle` writes two files into the run's own directory
//! beside its receipt, `.parley/receipts/<run>/`, where its sidecars go:
//!
//! - `bundle.json`, the `issue-dag-observations/1` bundle of every slot the
//!   gh adapter read ([`issue_dag_gh::GhForge::observations`]) under the
//!   run's parameters, written by [`issue_dag_bundle::dump`];
//! - `evaluation.json`, the run's `taskalisk-evaluation/1` record, made by
//!   [`issue_dag_bundle::evaluate`] from that bundle, so it retains it.
//!
//! Both hold issue bodies, so they are kept where the receipt is: under a
//! `.parley/.gitignore` of `*`, created new, and deleted with the receipt
//! by retention. Every declared secret's value is redacted from them first,
//! as from every line; one the redaction cannot reach refuses the capture.
//! The `git` adapter's branches are not observations of the profile, so no
//! bundle holds them (bundle rule OB12).
//!
//! `plan --from-bundle FILE` and `plan --from-record FILE` plan through a
//! [`RecordedForge`] alone: neither reads `gh` nor `git`. A bundle records
//! no title, URL or branch (OB12), so a replayed node shows
//! [`TITLE_NOT_RECORDED`], a null URL and no recoverable branch; the
//! decisions of the plan are the captured run's.

use std::fs;
use std::io::Read as _;
use std::path::Path;

use issue_dag_bundle::{
    Evaluator, Evaluators, Replay, dump, evaluate, load, replay as replay_record,
};
use issue_dag_core::{Bundle, Observations, Observed, Outcome, Parameters, RecordedForge, plan};
use issue_dag_gh::Shown;
use serde_json::{Value, json};

use crate::cli::{self, TOOL, VERSION};
use crate::parley::Run;
use crate::sha256;
use crate::views::View;

/// The title a replayed issue shows: a bundle records none (OB12).
pub const TITLE_NOT_RECORDED: &str = "(title not recorded in the bundle)";

/// What a replay plans from.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Source {
    /// An `issue-dag-observations/1` bundle (`--from-bundle`).
    Bundle,
    /// A `taskalisk-evaluation/1` record that retains its bundle
    /// (`--from-record`).
    Record,
}

impl Source {
    /// The flag that names it.
    #[must_use]
    pub const fn flag(self) -> &'static str {
        match self {
            Self::Bundle => "--from-bundle",
            Self::Record => "--from-record",
        }
    }

    /// The prefix of its error codes.
    const fn kind(self) -> &'static str {
        match self {
            Self::Bundle => "bundle",
            Self::Record => "evaluation",
        }
    }
}

/// This binary, as an evaluation record names it.
fn evaluator() -> Evaluator {
    Evaluator {
        name: TOOL.to_owned(),
        version: VERSION.to_owned(),
    }
}

fn evaluators(e: &Evaluators) -> Value {
    let one = |e: &Evaluator| json!({"name": e.name, "version": e.version});
    json!({"recorded": one(&e.recorded), "replaying": one(&e.replaying), "changed": e.changed()})
}

/// Writes the run's bundle and its retained evaluation record beside the
/// receipt, and records where in a receipt step. A capture that cannot be
/// made is a reported error: the run asked for it.
pub fn capture(run: &mut Run<'_>, parameters: &Parameters, observations: &Observations) {
    let failed = |run: &mut Run<'_>, why: &str| {
        run.error(
            "bundle.capture_failed",
            &cli::one_sentence(&format!("the observation bundle was not captured: {why}")),
            Some("make .parley/receipts writable, or rerun without --capture-bundle"),
            Some(false),
            Some(json!({"phase": "capture", "error": why})),
        );
    };
    let bundle = Bundle {
        parameters: parameters.clone(),
        observations: observations.clone(),
    };
    let mut value: Value = match serde_json::from_str(&dump(&bundle)) {
        Ok(value) => value,
        Err(e) => return failed(run, &e.to_string()),
    };
    let redacted = run.redact(&mut value);
    let text = value.to_string();
    let record = match evaluate(&text, &evaluator()) {
        Ok(record) => record,
        Err(e) => return failed(run, &e.to_string()),
    };
    let record_text = record.to_json();
    let stored = run.store("bundle.json", &text).and_then(|bundle| {
        run.store("evaluation.json", &record_text)
            .map(|record| (bundle, record))
    });
    let (bundle_path, record_path) = match stored {
        Ok(paths) => paths,
        Err(e) => return failed(run, &e.to_string()),
    };
    let file = |path: String, text: &str| json!({"path": path, "sha256": sha256::hex(text.as_bytes()), "bytes": text.len()});
    run.step(
        "captured the observation bundle and its evaluation record",
        "--capture-bundle: the bundle holds every slot the run read, issue bodies included, so plan --from-bundle or --from-record plans it again with reads disabled; both files are kept beside the receipt (paths relative to .parley/receipts/), where .parley/.gitignore keeps them out of git and retention deletes them with it; a declared secret's value is redacted first, at the pointers listed",
        Some(json!({
            "bundle": file(bundle_path, &text),
            "evaluation": file(record_path, &record_text),
            "outcome": record.result()["outcome"],
            "redacted": redacted,
        })),
    );
}

/// The largest bundle or record a replay reads, in bytes: 64 MiB. The
/// bundle of a thousand-issue backlog is a few megabytes; a larger file is
/// refused rather than read whole into memory.
pub const READ_LIMIT: u64 = 64 * 1024 * 1024;

/// The text of `path`, refused when it holds more than [`READ_LIMIT`]
/// bytes: by its size first, so a large file is not read, and by the bytes
/// read, so one that grows, or a pipe, is not read past the limit.
fn read_limited(path: &Path) -> std::io::Result<String> {
    let too_large = || {
        std::io::Error::new(
            std::io::ErrorKind::FileTooLarge,
            format!("the file is larger than the limit of {READ_LIMIT} bytes"),
        )
    };
    let file = fs::File::open(path)?;
    if file.metadata()?.len() > READ_LIMIT {
        return Err(too_large());
    }
    let mut text = String::new();
    file.take(READ_LIMIT + 1).read_to_string(&mut text)?;
    if text.len() as u64 > READ_LIMIT {
        return Err(too_large());
    }
    Ok(text)
}

/// Plans from the bundle or record at `path`, with reads disabled, and
/// writes the view `emit` asks for after the result lines.
pub fn replay(run: &mut Run<'_>, source: Source, path: &Path, emit: Option<View>) {
    let kind = source.kind();
    let text = match read_limited(path) {
        Ok(text) => text,
        Err(e) => {
            let problem = format!("{} {}: {e}", source.flag(), path.display());
            return run.error(
                &format!("{kind}.unreadable"),
                &cli::one_sentence(&cli::home_as_tilde(&problem)),
                Some("name a readable file of at most 64 MiB"),
                Some(false),
                Some(json!({
                    "source": source.flag(),
                    "error": cli::home_as_tilde(&e.to_string()),
                    "limit": READ_LIMIT,
                    "phase": "replay",
                })),
            );
        }
    };
    run.input(&text);
    let bundle_text = match source {
        Source::Bundle => text,
        Source::Record => match retained(run, &text) {
            Some(bundle) => bundle,
            None => return,
        },
    };
    let bundle = match load(&bundle_text) {
        Ok(bundle) => bundle,
        Err(e) => {
            return run.error(
                "bundle.invalid",
                &cli::one_sentence(&format!("not an issue-dag-observations/1 bundle: {e}")),
                Some("give a bundle that plan --capture-bundle wrote, or that the bundle rules OB1 to OB17 accept"),
                Some(false),
                Some(json!({"at": e.at, "problem": e.problem, "phase": "replay"})),
            );
        }
    };
    let outcome = match plan(
        &bundle.parameters,
        &RecordedForge::new(&bundle.observations),
    ) {
        Ok(outcome) => outcome,
        Err(missing) => {
            return run.error(
                "bundle.incomplete",
                &cli::one_sentence(&format!(
                    "the bundle is incomplete evidence: {missing}; a slot that was not recorded is never read as empty or unavailable (OB5)"
                )),
                Some("capture the bundle again; a recorder that leaves out a slot the run reads is a defect"),
                Some(false),
                Some(json!({"missing": missing.path, "what": missing.what, "phase": "replay"})),
            );
        }
    };
    run.step(
        "planned from the recorded observations with reads disabled",
        "the run reads only the bundle, through a recorded forge: no gh or git call is made, and a slot the bundle does not hold is missing, never empty",
        Some(json!({"source": source.flag(), "home": bundle.parameters.home.to_string()})),
    );
    conclude(
        run,
        &bundle.parameters,
        &bundle.observations,
        &outcome,
        emit,
    );
}

/// The bundle a record retains, once [`replay_record`] has planned it
/// again and found the recorded result; `None` after reporting why not.
fn retained(run: &mut Run<'_>, text: &str) -> Option<String> {
    let remedy = "capture the plan again with --capture-bundle";
    match replay_record(text, &evaluator()) {
        Err(e) => {
            run.error(
                "evaluation.invalid",
                &cli::one_sentence(&format!("not a taskalisk-evaluation/1 record: {e}")),
                Some("give the evaluation.json that plan --capture-bundle wrote"),
                Some(false),
                Some(json!({"at": e.at, "problem": e.problem, "phase": "replay"})),
            );
            None
        }
        Ok(Replay::Unavailable(why)) => {
            run.error(
                "evaluation.unavailable",
                &cli::one_sentence(&format!("the record cannot be replayed: {why}")),
                Some(remedy),
                Some(false),
                Some(json!({"unavailable": why, "phase": "replay"})),
            );
            None
        }
        Ok(Replay::Differs {
            recorded,
            recomputed,
            evaluators: e,
        }) => {
            run.error(
                "evaluation.differs",
                "the plan made again from the record's bundle differs from the result it records",
                Some(if e.changed() {
                    "the evaluator changed since the record was made; compare the two results"
                } else {
                    "the record or its bundle was changed after it was written; capture the plan again"
                }),
                Some(false),
                Some(json!({
                    "recorded_sha256": sha256::hex(recorded.as_bytes()),
                    "recomputed_sha256": sha256::hex(recomputed.as_bytes()),
                    "evaluators": evaluators(&e),
                    "phase": "replay",
                })),
            );
            None
        }
        Ok(Replay::Reproduced {
            result,
            evaluators: e,
        }) => {
            run.step(
                "replayed the evaluation record: the plan made again equals the recorded result",
                "issue-dag-bundle's replay plans the retained bundle offline and compares the result byte for byte (decision D14)",
                Some(json!({
                    "replay": "reproduced",
                    "result_sha256": sha256::hex(result.as_bytes()),
                    "evaluators": evaluators(&e),
                })),
            );
            let record: Value = serde_json::from_str(text).ok()?;
            Some(record["observations"]["value"].to_string())
        }
    }
}

/// The lines of a replayed outcome. An unavailable slot makes the run
/// incomplete (OB4), with the reason the bundle records.
fn conclude(
    run: &mut Run<'_>,
    parameters: &Parameters,
    observations: &Observations,
    outcome: &Outcome,
    emit: Option<View>,
) {
    match outcome {
        Outcome::Rejected(rejection) => cli::reject(run, rejection),
        Outcome::Incomplete {
            unavailable,
            cause: Some(cause),
        } => cli::not_found(run, unavailable, *cause, "bundle"),
        Outcome::Incomplete {
            unavailable,
            cause: None,
        } => run.error(
            "observation.unavailable",
            &cli::one_sentence(&format!(
                "the bundle records an observation the run needs as unavailable: {unavailable}"
            )),
            Some("capture a new bundle once the read succeeds; nothing was planned from a partial read"),
            Some(false),
            Some(json!({"unavailable": unavailable, "source": "bundle", "phase": "replay"})),
        ),
        Outcome::Invalid { .. } | Outcome::Planned { .. } => {
            let titles = observations
                .issues
                .iter()
                .filter(|(_, slot)| matches!(slot, Observed::Value(_)))
                .map(|(r, _)| (r.clone(), TITLE_NOT_RECORDED.to_owned()))
                .collect();
            let shown = Shown {
                titles,
                ..Shown::default()
            };
            let display = cli::display(shown, observations, parameters, &[]);
            cli::results(run, parameters, outcome, &display, emit);
        }
    }
}
