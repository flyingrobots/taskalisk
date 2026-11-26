//! The evaluation record, `taskalisk-evaluation/1`, and its replay rule
//! (flyingrobots/taskalisk#30; decision 0001, section 5).
//!
//! A record is the observation bundle a run planned from, the identity of
//! the evaluator that planned it, and the result. Beside them it names, so
//! that a record without its bundle still says them, the formats and the
//! profile, the discovery scope, and the facts the run could not observe.
//! The bundle is held whole and unchanged, in an observation slot (bundle
//! rule OB4): a record that did not retain it says why.
//!
//! ```json
//! {
//!   "record": "taskalisk-evaluation/1",
//!   "formats": ["issue-dag/2"],
//!   "profile": "issue-dag-planning/2",
//!   "evaluator": {"name": "taskalisk", "version": "0.1.0"},
//!   "discovery": {"home": "o/r", "roots": ["o/r#1"],
//!                 "read_scope": {"owners": ["o"], "repositories": []},
//!                 "trust_policy": "taskalisk/threat-model"},
//!   "not_observed": {"value": [{"at": "observations.issues[\"o/r#2\"]",
//!                               "unavailable": "HTTP 502"}]},
//!   "observations": {"value": {"bundle": "issue-dag-observations/1", "...": "..."}},
//!   "result": {"outcome": "planned", "...": "..."}
//! }
//! ```
//!
//! `result` is in the form of corpus rule CC6 ([`outcome_json`]). A record
//! is written as compact JSON with its members in ascending order, so one
//! run always writes the same bytes.
//!
//! **Replay** ([`replay`]) plans again from the retained bundle through a
//! [`RecordedForge`] alone: it takes no forge, so it cannot read anything
//! live. It is available only when the complete, lossless input is
//! retained. When the bundle is not retained, is not a bundle, lacks a slot
//! the run reads (OB5), or was planned under a format or profile this
//! evaluator does not implement, the answer is [`Replay::Unavailable`],
//! never a guess.

use core::fmt;
use std::collections::BTreeMap;

use issue_dag_core::{Missing, Observations, Observed, Outcome, Parameters, RecordedForge, plan};
use serde_json::{Value, json};

use crate::result::outcome_json;
use crate::{BundleError, FORMAT, PROFILE, Read, exact, fail, list, load, slot, strict, text};

/// The record version this crate writes and reads.
pub const RECORD_VERSION: &str = "taskalisk-evaluation/1";

/// The members of a record, every one required.
const MEMBERS: [&str; 8] = [
    "record",
    "formats",
    "profile",
    "evaluator",
    "discovery",
    "not_observed",
    "observations",
    "result",
];

/// The evaluator of a run: the planner's name and version.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Evaluator {
    /// The planner's name, such as `taskalisk`.
    pub name: String,
    /// Its version.
    pub version: String,
}

/// A well-formed evaluation record, held as the JSON it is written as.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EvaluationRecord {
    value: Value,
}

impl EvaluationRecord {
    /// Reads a record and checks its form: every member, and no other, of
    /// the kinds the module documentation shows. A record whose bundle is
    /// wrong is still read; [`replay`] judges the bundle.
    ///
    /// # Errors
    ///
    /// [`BundleError`] when the text is not JSON, gives a member twice, or
    /// is not a record.
    pub fn read(record_text: &str) -> Read<Self> {
        let value = strict::parse(record_text, "record")?;
        let r = exact(&value, "record", &MEMBERS, &[])?;
        if r["record"].as_str() != Some(RECORD_VERSION) {
            return fail("record", format!("must be {RECORD_VERSION:?}"));
        }
        let formats = list(&r["formats"], "formats")?;
        if formats.is_empty() {
            return fail("formats", "names no format");
        }
        for (i, f) in formats.iter().enumerate() {
            text(f, &format!("formats[{i}]"))?;
        }
        text(&r["profile"], "profile")?;
        let e = exact(&r["evaluator"], "evaluator", &["name", "version"], &[])?;
        text(&e["name"], "evaluator.name")?;
        text(&e["version"], "evaluator.version")?;
        let d = exact(
            &r["discovery"],
            "discovery",
            &["home", "roots", "read_scope", "trust_policy"],
            &[],
        )?;
        text(&d["home"], "discovery.home")?;
        list(&d["roots"], "discovery.roots")?;
        exact(
            &d["read_scope"],
            "discovery.read_scope",
            &["owners", "repositories"],
            &[],
        )?;
        text(&d["trust_policy"], "discovery.trust_policy")?;
        slot(&r["not_observed"], "not_observed", |v, at| {
            list(v, at).map(drop)
        })?;
        slot(&r["observations"], "observations", |v, at| {
            v.as_object()
                .map_or_else(|| fail(at, "not an object"), |_| Ok(()))
        })?;
        let result = exact(&r["result"], "result", &["outcome"], &RESULT_MEMBERS)?;
        text(&result["outcome"], "result.outcome")?;
        Ok(Self { value })
    }

    /// The record as compact JSON, members in ascending order.
    #[must_use]
    pub fn to_json(&self) -> String {
        self.value.to_string()
    }

    /// The result, in the form of corpus rule CC6.
    #[must_use]
    pub fn result(&self) -> &Value {
        &self.value["result"]
    }

    /// The evaluator the record names.
    #[must_use]
    pub fn evaluator(&self) -> Evaluator {
        let e = &self.value["evaluator"];
        let field = |k: &str| e[k].as_str().unwrap_or_default().to_owned();
        Evaluator {
            name: field("name"),
            version: field("version"),
        }
    }

    fn member(&self, name: &str) -> &Value {
        &self.value[name]
    }
}

/// The members a CC6 result may hold besides `outcome`.
const RESULT_MEMBERS: [&str; 16] = [
    "findings",
    "nodes",
    "containers",
    "unmodeled",
    "untrusted",
    "untrusted_pull_requests",
    "edges",
    "redundant",
    "not_planned",
    "ready",
    "scores",
    "waves",
    "critical_path",
    "batch",
    "skipped",
    "unknown_capacity",
];

/// Why a bundle gave no record.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EvaluationError {
    /// The bundle breaks a bundle rule.
    Bundle(BundleError),
    /// The bundle lacks a slot the run reads (OB5): the evidence is
    /// unusable, so the run has no result to record.
    Missing(Missing),
}

impl fmt::Display for EvaluationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Bundle(e) => write!(f, "the bundle is rejected: {e}"),
            Self::Missing(m) => write!(f, "the bundle is incomplete evidence: {m}"),
        }
    }
}

impl std::error::Error for EvaluationError {}

/// The evaluator that made a record and the one that replayed it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Evaluators {
    /// The evaluator the record names.
    pub recorded: Evaluator,
    /// The evaluator that planned again.
    pub replaying: Evaluator,
}

impl Evaluators {
    /// Whether the replaying evaluator is not the recorded one, by name or
    /// version. A difference in the result may then be the evaluator's,
    /// not the input's.
    #[must_use]
    pub fn changed(&self) -> bool {
        self.recorded != self.replaying
    }
}

/// The outcome of replaying a record.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Replay {
    /// The plan made again equals the recorded result, byte for byte.
    Reproduced {
        /// The result, as compact JSON.
        result: String,
        /// The recorded and the replaying evaluator.
        evaluators: Evaluators,
    },
    /// The plan made again differs from the recorded result.
    Differs {
        /// The recorded result, as compact JSON.
        recorded: String,
        /// The result made again, as compact JSON.
        recomputed: String,
        /// The recorded and the replaying evaluator, so that a difference
        /// shows whether the evaluator changed.
        evaluators: Evaluators,
    },
    /// The record does not retain the complete, lossless input of its run,
    /// or names a format or profile this evaluator does not implement. The
    /// text says why. No plan was made.
    Unavailable(String),
}

/// Plans offline from a bundle and records the run, the bundle retained.
///
/// # Errors
///
/// [`EvaluationError`] when the bundle is rejected, or lacks a slot the run
/// reads.
pub fn evaluate(
    bundle_text: &str,
    evaluator: &Evaluator,
) -> Result<EvaluationRecord, EvaluationError> {
    let retained = strict::parse(bundle_text, "bundle").map_err(EvaluationError::Bundle)?;
    let bundle = load(bundle_text).map_err(EvaluationError::Bundle)?;
    let outcome = plan(
        &bundle.parameters,
        &RecordedForge::new(&bundle.observations),
    )
    .map_err(EvaluationError::Missing)?;
    Ok(write(
        &bundle.parameters,
        &outcome,
        evaluator,
        Observed::Value((retained, not_observed(&bundle.observations))),
    ))
}

/// Records a run whose bundle was not retained, such as a live run with
/// capture off. Its replay is unavailable, for the reason `why`.
///
/// This is the hook for the binary's live `plan` (flyingrobots/taskalisk#31),
/// which emits a record for every run; capturing the bundle of a live run
/// is flyingrobots/taskalisk#59, after which a live run records through
/// [`evaluate`]'s form with the bundle retained.
#[must_use]
pub fn unretained(
    parameters: &Parameters,
    outcome: &Outcome,
    evaluator: &Evaluator,
    why: &str,
) -> EvaluationRecord {
    write(
        parameters,
        outcome,
        evaluator,
        Observed::Unavailable(why.to_owned()),
    )
}

fn write(
    parameters: &Parameters,
    outcome: &Outcome,
    evaluator: &Evaluator,
    retained: Observed<(Value, Value)>,
) -> EvaluationRecord {
    let (observations, not_observed) = match retained {
        Observed::Value((bundle, facts)) => (json!({"value": bundle}), json!({"value": facts})),
        Observed::Unavailable(why) => (json!({"unavailable": why}), json!({"unavailable": why})),
    };
    let value = json!({
        "record": RECORD_VERSION,
        "formats": [FORMAT],
        "profile": PROFILE,
        "evaluator": {"name": evaluator.name, "version": evaluator.version},
        "discovery": discovery(parameters),
        "not_observed": not_observed,
        "observations": observations,
        "result": Value::Object(outcome_json(outcome, &parameters.capacities)),
    });
    EvaluationRecord { value }
}

/// The discovery scope of a run: where it starts and what it may read
/// (profile rule I1).
fn discovery(parameters: &Parameters) -> Value {
    json!({
        "home": parameters.home.to_string(),
        "roots": parameters.roots,
        "read_scope": {
            "owners": parameters.read_scope.owners,
            "repositories": parameters
                .read_scope
                .repositories
                .iter()
                .map(ToString::to_string)
                .collect::<Vec<_>>(),
        },
        "trust_policy": parameters.trust.policy,
    })
}

/// Every unavailable slot of the observations, by its path in the bundle,
/// in ascending order of the path.
fn not_observed(o: &Observations) -> Value {
    let mut facts = BTreeMap::new();
    let mut note = |at: String, why: &String| {
        facts.insert(at, why.clone());
    };
    if let Some(Observed::Unavailable(why)) = &o.home_open_issues {
        note("observations.home_open_issues".to_owned(), why);
    }
    match &o.home_open_pull_requests {
        Some(Observed::Unavailable(why)) => {
            note("observations.home_open_pull_requests".to_owned(), why);
        }
        Some(Observed::Value(prs)) => {
            for (i, pr) in prs.iter().enumerate() {
                if let Observed::Unavailable(why) = &pr.draft {
                    note(
                        format!("observations.home_open_pull_requests[{i}].draft"),
                        why,
                    );
                }
            }
        }
        None => {}
    }
    for (r, issue) in &o.issues {
        if let Observed::Unavailable(why) = issue {
            note(format!("observations.issues[{:?}]", r.to_string()), why);
        }
    }
    for (r, body) in &o.bodies {
        if let Observed::Unavailable(why) = body {
            note(
                format!("observations.issues[{:?}].body", r.to_string()),
                why,
            );
        }
    }
    for (repo, logins) in &o.permissions {
        for (login, permission) in logins {
            if let Observed::Unavailable(why) = permission {
                note(
                    format!(
                        "observations.permissions[{:?}][{login:?}]",
                        repo.to_string()
                    ),
                    why,
                );
            }
        }
    }
    for (repo, file) in o.codeowners.iter().flatten() {
        if let Observed::Unavailable(why) = file {
            note(
                format!("observations.codeowners[{:?}]", repo.to_string()),
                why,
            );
        }
    }
    Value::Array(
        facts
            .into_iter()
            .map(|(at, why)| json!({"at": at, "unavailable": why}))
            .collect(),
    )
}

/// Replans from a record, offline, and compares the result with the
/// recorded one. Live reads are impossible: the run reads only the
/// retained bundle, through a [`RecordedForge`].
///
/// # Errors
///
/// [`BundleError`] when the text is not a record, or when the record
/// contradicts the bundle it retains: its formats, profile, discovery scope
/// or facts not observed are not the bundle's.
///
/// `evaluator` is the evaluator replaying; a result that is reproduced
/// or differs reports it beside the one the record names.
pub fn replay(record_text: &str, evaluator: &Evaluator) -> Read<Replay> {
    let record = EvaluationRecord::read(record_text)?;
    let retained = match slot(record.member("observations"), "observations", |v, _| {
        Ok(v.clone())
    })? {
        Observed::Value(bundle) => bundle,
        Observed::Unavailable(why) => {
            return Ok(Replay::Unavailable(format!(
                "the record does not retain its observations: {why}"
            )));
        }
    };
    if let Some(format) = retained.get("format")
        && *record.member("formats") != json!([format])
    {
        return fail("formats", "are not the format of the retained bundle");
    }
    if let Some(profile) = retained.get("profile")
        && record.member("profile") != profile
    {
        return fail("profile", "is not the profile of the retained bundle");
    }
    if *record.member("formats") != json!([FORMAT]) || record.member("profile") != PROFILE {
        return Ok(Replay::Unavailable(format!(
            "this evaluator plans {FORMAT} under {PROFILE}; the record names {} under {}",
            record.member("formats"),
            record.member("profile"),
        )));
    }
    let bundle = match load(&retained.to_string()) {
        Ok(bundle) => bundle,
        Err(e) => {
            return Ok(Replay::Unavailable(format!(
                "the retained observations are not a bundle: {e}"
            )));
        }
    };
    if *record.member("discovery") != discovery(&bundle.parameters) {
        return fail(
            "discovery",
            "is not the discovery scope of the retained bundle",
        );
    }
    if *record.member("not_observed") != json!({"value": not_observed(&bundle.observations)}) {
        return fail(
            "not_observed",
            "is not the unavailable slots of the retained bundle",
        );
    }
    let outcome = match plan(
        &bundle.parameters,
        &RecordedForge::new(&bundle.observations),
    ) {
        Ok(outcome) => outcome,
        Err(missing) => {
            return Ok(Replay::Unavailable(format!(
                "the retained observations are incomplete evidence: {missing}"
            )));
        }
    };
    let recomputed =
        Value::Object(outcome_json(&outcome, &bundle.parameters.capacities)).to_string();
    let recorded = record.result().to_string();
    let evaluators = Evaluators {
        recorded: record.evaluator(),
        replaying: evaluator.clone(),
    };
    Ok(if recorded == recomputed {
        Replay::Reproduced {
            result: recomputed,
            evaluators,
        }
    } else {
        Replay::Differs {
            recorded,
            recomputed,
            evaluators,
        }
    })
}
