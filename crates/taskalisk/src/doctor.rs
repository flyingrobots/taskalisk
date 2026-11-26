//! `taskalisk doctor --bundle FILE` (flyingrobots/taskalisk#49): every
//! finding of a recorded observation bundle, grouped by issue.
//!
//! The bundle is planned through a [`issue_dag_core::RecordedForge`] alone,
//! as `plan --from-bundle` plans it ([`crate::replay`]): no `gh` or `git`
//! call is made. Every family of findings is then read from the outcome:
//!
//! - **document** and **profile**: the findings the run itself reports
//!   (frontmatter rules C, L, V, P3 and X1; the run's D3, D4, D5, X2, X3, G4);
//! - **cause**: the part of a reference that resolves to nothing (D11 to
//!   D13), for an incomplete run whose bundle records it;
//! - **body**: [`issue_dag_core::body_warnings`] of each open issue the run
//!   admitted, without its title, which a bundle does not record;
//! - **shape** and **plan**: [`issue_dag_core::shape_warnings`] and
//!   [`issue_dag_core::plan_warnings`] of the run's graph, when it has one;
//! - **trust**: [`issue_dag_core::trust_findings`] of what discovery read.
//!
//! Its lines are a `taskalisk.doctor` summary, then one `taskalisk.doctor.issue`
//! line per subject: the issues and pull requests in the order of their
//! references, then the plan as a whole.
//!
//! Exit statuses: 0 no error finding (and, under `--strict`, no warning
//! finding); 1 an error finding, or under `--strict` a warning finding; 2 a
//! reported `parley.error`: the bundle cannot be read, is not a bundle, is
//! incomplete evidence (OB5), records an observation the run needs as
//! unavailable with no cause, or holds rejected run parameters; 3 a usage
//! error; 4 an output or receipt sink failure. Status 1 is free for this in
//! the Rust binary: the output contract reserves it only for the Python
//! script whose writer cannot be imported.

use std::collections::BTreeMap;
use std::io::Write;
use std::path::Path;

use issue_dag_core::{
    Bundle, Detail, Discovered, Finding, Graph, IssueState, LABELS, NotFound, Observed, Outcome,
    PlanDetail, Severity, body_warnings, code, plan_warnings, shape_warnings, trust_findings,
};
use serde_json::{Value, json};

use crate::cli::{self, SECRETS, TOOL, VERSION};
use crate::parley::{self, Run, Start, StartupFailure, schemas};
use crate::{human, replay};

/// How many receipts of this tool to keep, as `plan` keeps them.
const RETENTION: usize = 50;

const INTENT: &str = "Print every finding of a recorded issue-dag-observations/1 bundle, grouped by issue, and exit by the worst one (read-only; no gh or git read)";

/// The message schemas `doctor --help` describes.
const DESCRIBED: [(&str, &str); 4] = [
    (
        "taskalisk.doctor",
        include_str!("../../../skills/taskalisk/schemas/binary/taskalisk.doctor.schema.json"),
    ),
    (
        "taskalisk.doctor.issue",
        include_str!("../../../skills/taskalisk/schemas/binary/taskalisk.doctor.issue.schema.json"),
    ),
    (
        "parley.error",
        include_str!("../schemas/parley.error.schema.json"),
    ),
    (
        "parley.startup.failed",
        include_str!("../schemas/parley.startup.failed.schema.json"),
    ),
];

/// The schema of the summary line.
const SUMMARY: (&str, &str) = ("taskalisk.doctor", "1.0.0");
/// The schema of a subject's line.
const ISSUE: (&str, &str) = ("taskalisk.doctor.issue", "1.0.0");

/// The doctor's arguments, checked.
#[derive(Debug, Default)]
struct Arguments {
    bundle: Option<String>,
    strict: bool,
    human: bool,
    help: bool,
}

fn usage(problem: impl Into<String>) -> StartupFailure {
    StartupFailure {
        code: "startup.arguments_invalid",
        problem: problem.into(),
        remedy: "fix the arguments; see taskalisk doctor --help".to_owned(),
    }
}

fn parse(args: &[String]) -> Result<Arguments, StartupFailure> {
    let mut parsed = Arguments::default();
    let mut json = false;
    let mut i = 0;
    while i < args.len() {
        let (flag, inline) = match args[i].split_once('=') {
            Some((flag, value)) if flag.starts_with("--") => (flag, Some(value)),
            _ => (args[i].as_str(), None),
        };
        i += 1;
        if flag == "--bundle" {
            if parsed.bundle.is_some() {
                return Err(usage("give one --bundle"));
            }
            let value = if let Some(value) = inline {
                value.to_owned()
            } else {
                let value = args
                    .get(i)
                    .filter(|v| !v.starts_with('-') || v.len() == 1)
                    .ok_or_else(|| usage("--bundle expects a file"))?;
                i += 1;
                value.clone()
            };
            parsed.bundle = Some(value);
            continue;
        }
        let switch = match flag {
            "--strict" => &mut parsed.strict,
            "--json" => &mut json,
            "--human" | "--humanize" => &mut parsed.human,
            "--help" | "-h" => &mut parsed.help,
            other if other.starts_with('-') => {
                return Err(usage(format!(
                    "unrecognized argument {other}; doctor takes --bundle FILE, --strict, --json, --human and --help, each spelled in full"
                )));
            }
            other => return Err(usage(format!("unrecognized argument {other}"))),
        };
        if inline.is_some() {
            return Err(usage(format!("{flag} takes no value")));
        }
        *switch = true;
    }
    if json && parsed.human {
        return Err(usage(
            "--json and --human contradict each other: JSON lines are the default, --human prints prose",
        ));
    }
    if parsed.bundle.is_none() && !parsed.help {
        return Err(usage("doctor needs --bundle FILE"));
    }
    Ok(parsed)
}

/// Runs `doctor` with the arguments after the command and returns the exit
/// status.
pub fn main(
    args: &[String],
    cwd: &Path,
    secrets: &[String],
    secret_names: Vec<String>,
    stdout: &mut dyn Write,
    stderr: &mut dyn Write,
) -> u8 {
    let human_asked = args.iter().any(|a| a == "--human" || a == "--humanize");
    let arguments = match parse(args) {
        Ok(arguments) => arguments,
        Err(failure) => {
            return parley::startup_failed(TOOL, VERSION, &failure, human_asked, secrets, stderr);
        }
    };
    let file = arguments.bundle.as_ref().map(|f| cwd.join(f));
    let shown = file.as_ref().map(|f| cli::relative(f, cwd));
    let (resolved, inputs) = match (&shown, arguments.help) {
        (Some(shown), false) => (
            json!({
                "command": "doctor",
                "question": {"bundle": shown},
                "options": {"strict": arguments.strict},
            }),
            vec![json!({"path": shown, "role": "observations"})],
        ),
        _ => (
            json!({"discovery": "help", "command": "doctor"}),
            Vec::new(),
        ),
    };
    let start = Start {
        tool: TOOL,
        v: VERSION,
        command: "doctor",
        cwd,
        argv: [TOOL, "doctor"]
            .into_iter()
            .map(str::to_owned)
            .chain(args.iter().cloned())
            .collect(),
        resolved,
        inputs,
        effects: effects(shown.as_deref()),
        secrets: secrets.to_vec(),
        secret_names,
        human: arguments.human.then_some(prose as parley::Human),
        retention: RETENTION,
    };
    let mut run = match Run::start(start, stdout, stderr) {
        Ok(run) => run,
        Err(failure) => {
            return parley::startup_failed(TOOL, VERSION, &failure, human_asked, secrets, stderr);
        }
    };
    match file {
        Some(file) if !arguments.help => {
            let status = diagnose(&mut run, &file, arguments.strict);
            run.end_with(status)
        }
        _ => {
            help(&mut run);
            run.end()
        }
    }
}

/// What doctor reads and writes: the bundle alone, and nothing.
fn effects(bundle: Option<&str>) -> Value {
    json!({
        "reads": [bundle.unwrap_or("<bundle>")],
        "writes": [],
        "network": false,
        "idempotent": true,
    })
}

/// `doctor --help`: the command and the schemas of its results and errors.
fn help(run: &mut Run<'_>) {
    let emits: Vec<Value> = DESCRIBED
        .iter()
        .map(|(id, text)| json!({"id": id, "version": cli::schema_version(text)}))
        .collect();
    let mut effects = effects(None);
    effects["bookkeeping"] = run.bookkeeping();
    run.describe(
        json!({"event": "command", "name": "doctor", "intent": INTENT, "effects": effects,
               "secrets": SECRETS, "emits": emits}),
        schemas::COMMAND,
    );
    for (id, text) in DESCRIBED {
        let schema: Value = serde_json::from_str(text).unwrap_or(Value::Null);
        run.describe(
            json!({"event": "schema", "id": id, "version": cli::schema_version(text), "schema": schema}),
            schemas::SCHEMA,
        );
    }
}

/// Reads and plans the bundle at `file`, writes its findings, and returns
/// the status the run asks to end with: 1 when it is not ok, else 0. A
/// reported error ends the run with 2 whatever this returns.
fn diagnose(run: &mut Run<'_>, file: &Path, strict: bool) -> u8 {
    let Some(text) = replay::read(run, "--bundle", "bundle", file) else {
        return 0;
    };
    let Some((bundle, outcome)) = replay::planned(run, "--bundle", &text) else {
        return 0;
    };
    let (name, found) = match &outcome {
        Outcome::Rejected(rejection) => {
            cli::reject(run, rejection);
            return 0;
        }
        Outcome::Incomplete {
            unavailable,
            cause: None,
        } => {
            replay::unavailable(run, unavailable);
            return 0;
        }
        Outcome::Incomplete {
            unavailable,
            cause: Some(cause),
        } => (
            "incomplete",
            vec![cause_entry(&bundle, unavailable, *cause)],
        ),
        Outcome::Planned { findings, graph } => (
            "planned",
            entries(&bundle, findings, Some(graph), &graph.discovered()),
        ),
        Outcome::Invalid {
            findings,
            graph,
            discovered,
            ..
        } => (
            "invalid",
            entries(&bundle, findings, graph.as_ref(), discovered),
        ),
    };
    let groups = grouped(found);
    let count = |severity: Severity| -> usize {
        groups
            .values()
            .flatten()
            .filter(|e| e.severity == severity)
            .count()
    };
    let (errors, warnings) = (count(Severity::Error), count(Severity::Warning));
    let ok = errors == 0 && !(strict && warnings > 0);
    run.result(json!({
        "event": "doctor",
        "home": bundle.parameters.home.to_string(),
        "outcome": name,
        "errors": errors,
        "warnings": warnings,
        "strict": strict,
        "ok": ok,
        "_schema": parley::schema_ref(SUMMARY),
    }));
    for (key, group) in &groups {
        let count = |severity: Severity| group.iter().filter(|e| e.severity == severity).count();
        run.result(json!({
            "event": "doctor.issue",
            "subject": key.subject,
            "errors": count(Severity::Error),
            "warnings": count(Severity::Warning),
            "findings": group.iter().map(Entry::to_json).collect::<Vec<_>>(),
            "_schema": parley::schema_ref(ISSUE),
        }));
    }
    run.step(
        &format!("diagnosed the bundle: {errors} error(s), {warnings} warning(s)"),
        "doctor prints every finding family of the recorded bundle (document, profile, cause, body, shape, plan, trust); an error finding, or a warning under --strict, ends the run with status 1",
        Some(json!({"outcome": name, "strict": strict, "ok": ok})),
    );
    u8::from(!ok)
}

/// One finding as a doctor line carries it.
#[derive(Debug)]
struct Entry {
    code: &'static str,
    severity: Severity,
    family: &'static str,
    concerns: Option<String>,
    message: &'static str,
    detail: Option<Value>,
}

impl Entry {
    fn to_json(&self) -> Value {
        let mut line = json!({
            "code": self.code,
            "severity": self.severity.as_str(),
            "family": self.family,
            "message": self.message,
        });
        if let Some(concerns) = &self.concerns {
            line["concerns"] = json!(concerns);
        }
        if let Some(detail) = &self.detail {
            line["detail"] = detail.clone();
        }
        line
    }

    /// The order within a subject: the code, then the reference concerned,
    /// then the detail.
    fn order(&self) -> (&'static str, Option<&String>, String) {
        (
            self.code,
            self.concerns.as_ref(),
            self.detail
                .as_ref()
                .map_or_else(String::new, Value::to_string),
        )
    }
}

/// A subject's place in the output: issues and pull requests by their
/// repository, then their number; the plan as a whole last.
#[derive(Debug, PartialEq, Eq, PartialOrd, Ord)]
struct Key {
    plan: bool,
    repository: String,
    number: u64,
    subject: Option<String>,
}

impl Key {
    fn of(subject: Option<String>) -> Self {
        let (repository, number) = subject
            .as_deref()
            .and_then(|s| s.rsplit_once('#'))
            .map_or((String::new(), 0), |(repository, number)| {
                (repository.to_owned(), number.parse().unwrap_or(0))
            });
        Self {
            plan: subject.is_none(),
            repository,
            number,
            subject,
        }
    }
}

/// The findings by subject, each group in [`Entry::order`].
fn grouped(found: Vec<(Option<String>, Entry)>) -> BTreeMap<Key, Vec<Entry>> {
    let mut groups: BTreeMap<Key, Vec<Entry>> = BTreeMap::new();
    for (subject, entry) in found {
        groups.entry(Key::of(subject)).or_default().push(entry);
    }
    for group in groups.values_mut() {
        group.sort_by(|a, b| a.order().cmp(&b.order()));
    }
    groups
}

/// A finding with a subject, of `family`.
fn finding(
    finding: &Finding,
    family: &'static str,
    detail: Option<Value>,
) -> (Option<String>, Entry) {
    (
        Some(finding.subject.to_string()),
        Entry {
            code: finding.code().as_str(),
            severity: finding.severity(),
            family,
            concerns: finding.concerns.as_ref().map(ToString::to_string),
            message: finding.message,
            detail,
        },
    )
}

/// Whether a code is a document's: a label's code, X1 included.
fn is_document_code(text: &str) -> bool {
    LABELS.iter().any(|label| code(*label) == text)
}

/// Every finding of a run that planned, or that is invalid: its own
/// findings, the body warnings of each open issue it admitted, the shape
/// and plan warnings of its graph, and its trust warnings.
fn entries(
    bundle: &Bundle,
    findings: &std::collections::BTreeSet<Finding>,
    graph: Option<&Graph>,
    discovered: &Discovered,
) -> Vec<(Option<String>, Entry)> {
    let mut out: Vec<(Option<String>, Entry)> = findings
        .iter()
        .map(|f| {
            let family = if is_document_code(f.code().as_str()) {
                "document"
            } else {
                "profile"
            };
            finding(f, family, None)
        })
        .collect();
    out.extend(bodies(bundle, discovered));
    if let Some(graph) = graph {
        for shape in shape_warnings(graph) {
            let detail = match &shape.detail {
                Some(Detail::ImpliedVia(via)) => Some(json!({"implied_via": via.to_string()})),
                _ => None,
            };
            out.push(finding(&shape.finding, "shape", detail));
        }
        for warning in plan_warnings(graph) {
            let detail = match warning.detail {
                PlanDetail::Density {
                    reduced_edges,
                    open_nodes,
                    density,
                    band,
                } => Some(json!({
                    "reduced_edges": reduced_edges,
                    "open_nodes": open_nodes,
                    "density": density,
                    "band": [band.0, band.1],
                })),
                _ => None,
            };
            out.push((
                None,
                Entry {
                    code: warning.code().as_str(),
                    severity: warning.severity(),
                    family: "plan",
                    concerns: None,
                    message: warning.message,
                    detail,
                },
            ));
        }
    }
    for trust in trust_findings(discovered) {
        out.push((
            Some(trust.subject.to_string()),
            Entry {
                code: trust.code().as_str(),
                severity: trust.severity(),
                family: "trust",
                concerns: None,
                message: trust.message,
                detail: Some(json!({"login": trust.login, "rule": trust.rule})),
            },
        ));
    }
    out
}

/// The body warnings of each open issue the run visited and admitted, at
/// its address. An untrusted issue's body is never judged, even when it
/// was read; nor is a closed issue's.
fn bodies(bundle: &Bundle, discovered: &Discovered) -> Vec<(Option<String>, Entry)> {
    let observations = &bundle.observations;
    let mut out = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    for reference in &discovered.visit_order {
        if !seen.insert(reference) || discovered.untrusted_issue_reasons.contains_key(reference) {
            continue;
        }
        let (Some(Observed::Value(issue)), Some(Observed::Value(body))) = (
            observations.issues.get(reference),
            observations.bodies.get(reference),
        ) else {
            continue;
        };
        if issue.pull_request
            || issue.state != IssueState::Open
            || discovered
                .untrusted_issue_reasons
                .contains_key(&issue.address)
        {
            continue;
        }
        for warning in body_warnings(&body.text, &issue.address, None) {
            out.push(finding(&warning, "body", None));
        }
    }
    out
}

/// The cause of an incomplete run as a finding: its catalogued code, about
/// the reference whose slot records it.
fn cause_entry(bundle: &Bundle, unavailable: &str, cause: NotFound) -> (Option<String>, Entry) {
    let observations = &bundle.observations;
    let recorded = |strict: bool| {
        observations
            .not_found
            .iter()
            .filter(|(_, c)| **c == cause)
            .find(|(reference, _)| {
                !strict
                    || matches!(observations.issues.get(*reference), Some(Observed::Unavailable(why)) if why == unavailable)
            })
            .map(|(reference, _)| reference.to_string())
    };
    let subject = recorded(true).or_else(|| recorded(false));
    let message = match cause {
        NotFound::Owner => {
            "a reference resolves to nothing: no account has its owner's login (profile rule D11); the run is incomplete"
        }
        NotFound::Repository => {
            "a reference resolves to nothing: its owner has no repository of that name (profile rule D12); the run is incomplete"
        }
        NotFound::Number => {
            "a reference resolves to nothing: its repository has no issue or pull request of that number (profile rule D13); the run is incomplete"
        }
    };
    let code = cause.code();
    (
        subject,
        Entry {
            code: code.as_str(),
            severity: code.severity(),
            family: "cause",
            concerns: None,
            message,
            detail: Some(json!({
                "rule": cause.label(),
                "not_found": cause.as_str(),
                "unavailable": unavailable,
            })),
        },
    )
}

/// A doctor line as prose for `--human`; every other line as `plan`
/// prints it. GitHub text is escaped ([`human::hs`]).
fn prose(line: &Value) -> Option<String> {
    match line["event"].as_str()? {
        "doctor" => {
            let mut out = format!(
                "{}: {}, {} error(s), {} warning(s)",
                human::hs(&line["home"]),
                human::hs(&line["outcome"]),
                line["errors"],
                line["warnings"]
            );
            if line["strict"] == Value::Bool(true) {
                out.push_str(" (--strict: a warning counts as an error)");
            }
            if line["ok"] != Value::Bool(true) {
                out.push_str("\nNOT OK");
            }
            Some(out)
        }
        "doctor.issue" => {
            let mut out = vec![
                String::new(),
                line["subject"]
                    .as_str()
                    .map_or_else(|| "the plan".to_owned(), |s| human::hs(&json!(s))),
            ];
            for f in line["findings"].as_array().into_iter().flatten() {
                let concerns = f
                    .get("concerns")
                    .map_or_else(String::new, |c| format!(" (concerns {})", human::hs(c)));
                let detail = f["detail"]
                    .as_object()
                    .map(|d| {
                        d.iter()
                            .map(|(k, v)| format!("{}={}", human::hs(&json!(k)), human::hs(v)))
                            .collect::<Vec<_>>()
                            .join(", ")
                    })
                    .filter(|d| !d.is_empty())
                    .map_or_else(String::new, |d| format!(" [{d}]"));
                out.push(format!(
                    "  {} {}{concerns}: {}{detail}",
                    human::hs(&f["severity"]),
                    human::hs(&f["code"]),
                    human::hs(&f["message"])
                ));
            }
            Some(out.join("\n"))
        }
        _ => human::render(line),
    }
}

#[cfg(test)]
mod tests {
    use super::{DESCRIBED, parse, prose};
    use issue_dag_core::{CODES, Severity};
    use serde_json::{Value, json};

    fn strings(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| (*s).to_owned()).collect()
    }

    /// The finding codes a doctor line may carry are the catalogue's, in
    /// its order: a new family's codes cannot be printed until the schema
    /// lists them.
    #[test]
    fn the_schema_lists_the_catalogue_codes_in_order() {
        let (_, text) = DESCRIBED[1];
        let schema: Value = serde_json::from_str(text).expect("JSON");
        let listed: Vec<&str> =
            schema["properties"]["findings"]["items"]["properties"]["code"]["enum"]
                .as_array()
                .expect("an enum")
                .iter()
                .filter_map(Value::as_str)
                .collect();
        let catalogue: Vec<&str> = CODES.iter().map(|(code, _)| *code).collect();
        assert_eq!(listed, catalogue);
        let severities: Vec<&str> =
            schema["properties"]["findings"]["items"]["properties"]["severity"]["enum"]
                .as_array()
                .expect("an enum")
                .iter()
                .filter_map(Value::as_str)
                .collect();
        assert_eq!(
            severities,
            [Severity::Error.as_str(), Severity::Warning.as_str()]
        );
    }

    #[test]
    fn the_arguments_are_checked() {
        let parsed = parse(&strings(&["--bundle", "b.json", "--strict"])).expect("valid");
        assert_eq!(parsed.bundle.as_deref(), Some("b.json"));
        assert!(parsed.strict && !parsed.human);
        assert!(parse(&strings(&["--bundle=b.json", "--json"])).is_ok());
        assert!(parse(&strings(&["--help"])).is_ok_and(|p| p.help));
        for bad in [
            &[][..],
            &["--bundle"],
            &["--bundle", "--strict"],
            &["--bundle", "a", "--bundle", "b"],
            &["--bundle", "a", "--json", "--human"],
            &["--bundle", "a", "--strict=1"],
            &["--bundle", "a", "--from-bundle", "a"],
            &["--bundle", "a", "x"],
        ] {
            assert!(parse(&strings(bad)).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn prose_escapes_github_text_in_every_field() {
        let line = json!({"event": "doctor.issue", "subject": "o/r#2", "findings": [{
            "code": "taskalisk.untrusted-editor", "severity": "warning", "family": "trust",
            "message": "m", "detail": {"login": "a\u{202e}b\nc", "rule": "AD5.7"},
        }]});
        let text = prose(&line).expect("prose");
        assert_eq!(
            text,
            "\no/r#2\n  warning taskalisk.untrusted-editor: m [login=a\\u202eb\\u000ac, rule=AD5.7]"
        );
        let plan = json!({"event": "doctor.issue", "subject": null, "findings": []});
        assert_eq!(prose(&plan).as_deref(), Some("\nthe plan"));
    }
}
