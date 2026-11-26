//! The `taskalisk` command line and its one command, `plan`.
//!
//! `plan` reads a live backlog through the `gh` and `git` adapters, plans
//! it with `issue-dag-core`, and writes the rendered lines under the Parley
//! envelope with a receipt (flyingrobots/taskalisk#31).
//!
//! It accepts the Python compiler's plan-mode flags where the core supports
//! them: `--repo`, `--root`, `--sem-capacity`, `--trust`, `--trust-owner`,
//! `--trust-repo`, `--trust-codeowners`, `--from-github` (which selects
//! `plan`, as in 1.x), and the writer's `--human` and `--help`. Every other
//! flag of the Python's, and every other command, is refused before the run
//! starts (exit 3), never ignored.
//!
//! Its own flags capture and replay a plan's observations
//! (flyingrobots/taskalisk#59, [`crate::replay`]): `--capture-bundle`
//! saves the bundle a live plan was made from; `--from-bundle FILE` and
//! `--from-record FILE` plan from a bundle or an evaluation record, as
//! `--from-github` plans from GitHub, with no `gh` or `git` read; and
//! `--offline` disables those reads, so that a run with no recorded source
//! is an error (exit 2) rather than a live read.
//!
//! Exit statuses: 0 success, 2 a reported error, 3 a usage error, 4 an
//! output or receipt sink failure.

use std::collections::{BTreeMap, BTreeSet};
use std::ffi::OsString;
use std::io::Write;
use std::path::{Component, Path, PathBuf};

use issue_dag_bundle::{Evaluator, unretained};
use issue_dag_core::{
    Cause, Identity, IssueRef, IssueState, NotFound, Observations, Observed, Outcome, Parameters,
    ReadScope, Rejection, Repo, TRUST_POLICY, TrustParameters, codeowners_persons, is_name, plan,
};
use issue_dag_gh::{GhError, GhForge, Shown, repository_of};
use issue_dag_git::{GitError, GitRepository};
use serde_json::{Value, json};

use crate::parley::{self, Run, Start, StartupFailure, schemas};
use crate::render::{self, Display};
use crate::replay::{self, Source};
use crate::{human, sha256};

/// The tool's name in every line and receipt: the Python's, because this
/// binary is the same tool under the same output contract (decision 0002).
pub const TOOL: &str = "taskalisk";
/// The binary's version.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
/// Receipts of this tool kept in a receipt directory.
const RETENTION: usize = 50;
/// The declared input of a plan: the issues discovery observed.
const OBSERVATIONS_INPUT: &str = "github:issues";
/// Every token variable `gh help environment` names.
const SECRETS: [&str; 4] = [
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
];
const INTENT: &str = "Compile issue-dag/2 frontmatter from GitHub into a reduced DAG, rank the open frontier and propose a conflict-free batch (read-only; --from-github)";
const READS: [&str; 5] = [
    "github:issues and their body edit history",
    "github:pull-requests",
    "github:collaborator-permissions",
    "github:CODEOWNERS (--trust-codeowners)",
    "<repo> git branches",
];
const COMMANDS: [&str; 4] = ["plan", "edit", "verify", "inventory"];
/// The Python's flags that take a value.
const VALUE_FLAGS: [&str; 12] = [
    "--repo",
    "--milestone",
    "--root",
    "--sem-capacity",
    "--verify-dag",
    "--min-confidence",
    "--add-edge",
    "--remove-edge",
    "--reason",
    "--trust",
    "--trust-owner",
    "--trust-repo",
];
/// This binary's own flags that take a value: the recorded sources of a
/// replay (flyingrobots/taskalisk#59). The Python has none.
const OWN_VALUE_FLAGS: [&str; 2] = ["--from-bundle", "--from-record"];
/// The flags whose values a bundle already records, refused in a replay.
const ANSWERED_BY_THE_BUNDLE: [&str; 9] = [
    "--repo",
    "--root",
    "--sem-capacity",
    "--trust",
    "--trust-owner",
    "--trust-repo",
    "--trust-codeowners",
    "--from-github",
    "--capture-bundle",
];
/// The Python's flags this binary refuses: the core or the binary cannot
/// honour them yet.
const REFUSED: [&str; 12] = [
    "--milestone",
    "--verify-dag",
    "--min-confidence",
    "--add-edge",
    "--remove-edge",
    "--reason",
    "--compare-relationships",
    "--emit-mermaid",
    "--emit-roadmap",
    "--since-last",
    "--dry-run",
    "--schema",
];

/// The message schemas `plan --help` describes: the result lines it writes
/// and the errors it can report.
const DESCRIBED: [(&str, &str); 9] = [
    (
        "taskalisk.plan",
        include_str!("../../../skills/taskalisk/schemas/taskalisk.plan.schema.json"),
    ),
    (
        "taskalisk.frontier_node",
        include_str!("../../../skills/taskalisk/schemas/taskalisk.frontier_node.schema.json"),
    ),
    (
        "taskalisk.batch",
        include_str!("../../../skills/taskalisk/schemas/taskalisk.batch.schema.json"),
    ),
    (
        "taskalisk.node",
        include_str!("../../../skills/taskalisk/schemas/taskalisk.node.schema.json"),
    ),
    (
        "taskalisk.wave",
        include_str!("../../../skills/taskalisk/schemas/taskalisk.wave.schema.json"),
    ),
    (
        "taskalisk.edge",
        include_str!("../../../skills/taskalisk/schemas/taskalisk.edge.schema.json"),
    ),
    (
        "taskalisk.finding",
        include_str!("../../../skills/taskalisk/schemas/taskalisk.finding.schema.json"),
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

/// The writer's own flags a run was given.
#[derive(Debug, Default)]
struct WriterFlags {
    /// `--human`: prose on the streams, the receipt unchanged.
    human: bool,
    /// `--help`: describe the command and its schemas.
    help: bool,
}

/// The plan command's arguments, checked.
#[derive(Debug, Default)]
struct Arguments {
    /// The argument vector with the command first, as the receipt shows it.
    argv: Vec<String>,
    inferred: bool,
    writer: WriterFlags,
    repo: Option<String>,
    roots: Vec<String>,
    capacities: Vec<String>,
    trust: Vec<String>,
    trust_owners: Vec<String>,
    trust_repos: Vec<String>,
    trust_codeowners: bool,
    /// `--from-bundle` or `--from-record`, and its file.
    replay: Option<(Source, String)>,
    /// The flags given, by name: `--capture-bundle` and `--offline` are read
    /// from here, and a replay refuses those its bundle answers.
    given: BTreeSet<String>,
}

impl Arguments {
    /// `--capture-bundle`: save the bundle a live plan was made from.
    fn capture_bundle(&self) -> bool {
        self.given.contains("--capture-bundle")
    }

    /// `--offline`: no `gh` or `git` read.
    fn offline(&self) -> bool {
        self.given.contains("--offline")
    }
}

fn usage(problem: impl Into<String>) -> StartupFailure {
    StartupFailure {
        code: "startup.arguments_invalid",
        problem: problem.into(),
        remedy: "fix the arguments; see taskalisk plan --help".to_owned(),
    }
}

fn unsupported(what: &str) -> StartupFailure {
    StartupFailure {
        code: "startup.arguments_invalid",
        problem: format!("{what} is not supported by the Rust binary yet"),
        remedy: "run skills/taskalisk/scripts/taskalisk.py for it".to_owned(),
    }
}

/// Splits `--flag=value`.
fn split(arg: &str) -> (&str, Option<&str>) {
    match arg.split_once('=') {
        Some((flag, value)) if flag.starts_with("--") => (flag, Some(value)),
        _ => (arg, None),
    }
}

/// The command and the rest, as 1.x selects it: a command named first, or
/// as the first positional argument, or inferred from the mode flags.
fn command(args: &[String]) -> (Option<String>, Vec<String>, bool) {
    if let Some(first) = args.first().filter(|a| COMMANDS.contains(&a.as_str())) {
        return (Some(first.clone()), args[1..].to_vec(), false);
    }
    let mut i = 0;
    while i < args.len() {
        let (flag, value) = split(&args[i]);
        if flag.starts_with('-') {
            let takes_value = VALUE_FLAGS.contains(&flag) || OWN_VALUE_FLAGS.contains(&flag);
            i += if takes_value && value.is_none() { 2 } else { 1 };
            continue;
        }
        if COMMANDS.contains(&flag) {
            let mut rest = args[..i].to_vec();
            rest.extend_from_slice(&args[i + 1..]);
            return (Some(args[i].clone()), rest, false);
        }
        break;
    }
    let has = |name: &str| args.iter().any(|a| split(a).0 == name);
    let inferred = if has("--add-edge") || has("--remove-edge") {
        "edit"
    } else if has("--from-github") || OWN_VALUE_FLAGS.iter().any(|f| has(f)) {
        "plan"
    } else if has("--verify-dag") {
        "verify"
    } else if has("--help") || has("-h") {
        return (None, args.to_vec(), false);
    } else {
        "inventory"
    };
    (Some(inferred.to_owned()), args.to_vec(), true)
}

fn parse(raw: &[String]) -> Result<Arguments, StartupFailure> {
    let (name, rest, inferred) = command(raw);
    let mut parsed = Arguments {
        inferred,
        ..Arguments::default()
    };
    match name.as_deref() {
        Some("plan") | None => {}
        Some(other) => {
            return Err(unsupported(&format!("the {other} command")));
        }
    }
    parsed.argv = std::iter::once("plan".to_owned())
        .chain(rest.iter().cloned())
        .collect();
    let mut i = 0;
    while i < rest.len() {
        let (flag, inline) = split(&rest[i]);
        i += 1;
        match flag {
            "--human" | "--humanize" => parsed.writer.human = true,
            "--help" | "-h" => parsed.writer.help = true,
            _ => {}
        }
        if matches!(flag, "--human" | "--humanize" | "--help" | "-h") {
            if inline.is_some() {
                return Err(usage(format!("{flag} takes no value")));
            }
            continue;
        }
        if REFUSED.contains(&flag) {
            return Err(unsupported(flag));
        }
        parsed.given.insert(flag.to_owned());
        if matches!(
            flag,
            "--from-github" | "--trust-codeowners" | "--capture-bundle" | "--offline"
        ) {
            if inline.is_some() {
                return Err(usage(format!("{flag} takes no value")));
            }
            parsed.trust_codeowners |= flag == "--trust-codeowners";
            continue;
        }
        if !VALUE_FLAGS.contains(&flag) && !OWN_VALUE_FLAGS.contains(&flag) {
            return Err(usage(if flag.starts_with('-') {
                format!("unrecognized argument {flag}; every flag is spelled in full")
            } else {
                format!("unrecognized argument {flag}")
            }));
        }
        let value = if let Some(value) = inline {
            value.to_owned()
        } else {
            let value = rest
                .get(i)
                .filter(|v| !v.starts_with('-') || v.len() == 1)
                .ok_or_else(|| usage(format!("{flag} expects a value")))?;
            i += 1;
            value.clone()
        };
        match flag {
            "--repo" => parsed.repo = Some(value),
            "--root" => parsed.roots.push(value),
            "--sem-capacity" => parsed.capacities.push(value),
            "--trust" => parsed.trust.push(value),
            "--trust-owner" => parsed.trust_owners.push(value),
            "--from-bundle" => parsed.replay = Some((Source::Bundle, value)),
            "--from-record" => parsed.replay = Some((Source::Record, value)),
            _ => parsed.trust_repos.push(value),
        }
    }
    if parsed.writer.help {
        return Ok(parsed);
    }
    contradictions(&parsed, &rest)?;
    if capacities(&parsed.capacities).is_none() {
        return Err(usage("--sem-capacity takes name=N with N >= 1"));
    }
    if parsed.trust_owners.iter().any(|o| !is_name(o))
        || parsed.trust_repos.iter().any(|r| Repo::parse(r).is_none())
    {
        return Err(usage(
            "--trust-owner takes an owner name; --trust-repo takes owner/repo",
        ));
    }
    if let Some(root) = parsed.roots.iter().find(|r| IssueRef::parse(r).is_none()) {
        return Err(usage(format!(
            "--root {root:?} is not a reference (use owner/repo#N; bare numbers are not allowed)"
        )));
    }
    Ok(parsed)
}

/// The capture and replay flags that contradict each other or the run
/// parameters a recorded bundle already holds (flyingrobots/taskalisk#59).
fn contradictions(parsed: &Arguments, rest: &[String]) -> Result<(), StartupFailure> {
    let sources = rest
        .iter()
        .filter(|a| OWN_VALUE_FLAGS.contains(&split(a).0))
        .count();
    if sources > 1 {
        return Err(usage(
            "give one recorded source: one --from-bundle or one --from-record",
        ));
    }
    if let Some((source, _)) = &parsed.replay
        && let Some(flag) = ANSWERED_BY_THE_BUNDLE
            .iter()
            .find(|f| parsed.given.contains(**f))
    {
        return Err(usage(format!(
            "{flag} cannot be given with {}: the recorded bundle holds the run's repository, roots, trust and capacities, and a replay reads nothing live",
            source.flag()
        )));
    }
    if parsed.offline() && parsed.capture_bundle() {
        return Err(usage(
            "--capture-bundle captures a live read, which --offline disables",
        ));
    }
    Ok(())
}

/// `name=N` with `N >= 1`, each; `None` when one is not.
fn capacities(items: &[String]) -> Option<BTreeMap<String, u64>> {
    let mut out = BTreeMap::new();
    for item in items {
        let (name, number) = item.split_once('=').unwrap_or((item, ""));
        let n: u64 = number
            .bytes()
            .all(|b| b.is_ascii_digit())
            .then(|| number.parse().ok())
            .flatten()?;
        if name.is_empty() || n < 1 {
            return None;
        }
        out.insert(name.to_owned(), n);
    }
    Some(out)
}

/// Runs the command line and returns the exit status.
pub fn main(args: &[OsString], cwd: &Path, stdout: &mut dyn Write, stderr: &mut dyn Write) -> u8 {
    let raw: Vec<String> = args
        .iter()
        .skip(1)
        .map(|a| a.to_string_lossy().into_owned())
        .collect();
    let human_asked = raw.iter().any(|a| a == "--human" || a == "--humanize");
    let secret_names: Vec<String> = SECRETS
        .iter()
        .filter(|name| std::env::var_os(name).is_some())
        .map(|&name| name.to_owned())
        .collect();
    let secrets: Vec<String> = SECRETS
        .iter()
        .filter_map(|name| std::env::var(name).ok())
        .filter(|value| !value.is_empty())
        .collect();
    if args.iter().skip(1).any(|a| a.to_str().is_none()) {
        let failure = usage("an argument is not UTF-8");
        return parley::startup_failed(TOOL, VERSION, &failure, human_asked, &secrets, stderr);
    }
    let arguments = match parse(&raw) {
        Ok(arguments) => arguments,
        Err(failure) => {
            return parley::startup_failed(TOOL, VERSION, &failure, human_asked, &secrets, stderr);
        }
    };
    let repo_dir = cwd.join(arguments.repo.as_deref().unwrap_or("."));
    let recorded = arguments
        .replay
        .as_ref()
        .map(|(source, file)| (*source, cwd.join(file)));
    let resolved = match &recorded {
        _ if arguments.writer.help => json!({"discovery": "help", "command": "plan"}),
        Some((source, file)) => json!({
            "command": "plan",
            "question": {source.flag().trim_start_matches("--from-"): relative(file, cwd)},
        }),
        None => resolved(&arguments, cwd, &repo_dir),
    };
    let inputs = match &recorded {
        _ if arguments.writer.help => Vec::new(),
        Some((_, file)) => vec![json!({"path": relative(file, cwd), "role": "observations"})],
        None => vec![json!({"path": OBSERVATIONS_INPUT, "role": "observations"})],
    };
    let start = Start {
        tool: TOOL,
        v: VERSION,
        command: "plan",
        cwd,
        argv: std::iter::once(TOOL.to_owned())
            .chain(arguments.argv.iter().cloned())
            .collect(),
        resolved,
        inputs,
        effects: effects(&arguments, cwd),
        secrets: secrets.clone(),
        secret_names,
        human: arguments
            .writer
            .human
            .then_some(human::render as parley::Human),
        retention: RETENTION,
    };
    let mut run = match Run::start(start, stdout, stderr) {
        Ok(run) => run,
        Err(failure) => {
            return parley::startup_failed(TOOL, VERSION, &failure, human_asked, &secrets, stderr);
        }
    };
    if arguments.writer.help {
        help(&mut run);
    } else {
        if arguments.inferred {
            run.step(
                "command plan inferred from the 1.x mode flags",
                "no command was named; --add-edge or --remove-edge means edit, --from-github plan, --verify-dag verify, none of them inventory",
                None,
            );
        }
        match recorded {
            Some((source, file)) => replay::replay(&mut run, source, &file),
            None if arguments.offline() => run.error(
                "plan.reads_disabled",
                "--offline disables the gh and git reads, and no recorded source was given",
                Some("add --from-bundle FILE or --from-record FILE, or drop --offline to read GitHub"),
                Some(false),
                Some(json!({"phase": "discovery"})),
            ),
            None => plan_live(&mut run, &arguments, &repo_dir),
        }
    }
    run.end()
}

/// What the run reads and writes: a live plan reads GitHub and git, and
/// with `--capture-bundle` writes its bundle and record beside the receipt;
/// a replay reads its file alone, and `--offline` reads nothing.
fn effects(arguments: &Arguments, cwd: &Path) -> Value {
    match &arguments.replay {
        Some((_, file)) => json!({
            "reads": [relative(&cwd.join(file), cwd)], "writes": [], "network": false, "idempotent": true,
        }),
        None if arguments.offline() => {
            json!({"reads": [], "writes": [], "network": false, "idempotent": true})
        }
        None => {
            let writes: &[&str] = if arguments.capture_bundle() {
                &[
                    ".parley/receipts/<run>/bundle.json",
                    ".parley/receipts/<run>/evaluation.json",
                ]
            } else {
                &[]
            };
            json!({"reads": READS, "writes": writes, "network": true, "idempotent": true})
        }
    }
}

/// The resolved question: what the run was asked, with no clock, path
/// outside `--repo`, or secret.
fn resolved(arguments: &Arguments, cwd: &Path, repo_dir: &Path) -> Value {
    let lower = |items: &[String]| -> BTreeSet<String> {
        items.iter().map(|i| i.to_ascii_lowercase()).collect()
    };
    let logins: BTreeSet<String> = arguments
        .trust
        .iter()
        .map(|entry| {
            let identity = Identity::of_entry(entry);
            if identity.bot {
                format!("bot:{}", identity.name)
            } else {
                identity.name
            }
        })
        .collect();
    let mut roots = arguments.roots.clone();
    roots.sort();
    let mut capacities = arguments.capacities.clone();
    capacities.sort();
    json!({
        "command": "plan",
        "question": {
            "repo": relative(repo_dir, cwd),
            "roots": roots,
            "trust": {
                "owners": lower(&arguments.trust_owners),
                "repos": lower(&arguments.trust_repos),
                "logins": logins,
                "codeowners": arguments.trust_codeowners,
            },
        },
        "options": {"emit": null, "compare_relationships": false, "since_last": false, "sem_capacity": capacities},
    })
}

/// `path` relative to `base`, both resolved, as `os.path.relpath` writes it.
fn relative(path: &Path, base: &Path) -> String {
    let resolve = |p: &Path| p.canonicalize().unwrap_or_else(|_| p.to_owned());
    let (path, base) = (resolve(path), resolve(base));
    let to: Vec<Component<'_>> = path.components().collect();
    let from: Vec<Component<'_>> = base.components().collect();
    let common = to.iter().zip(&from).take_while(|(a, b)| a == b).count();
    let mut out = PathBuf::new();
    for _ in common..from.len() {
        out.push("..");
    }
    for part in &to[common..] {
        out.push(part);
    }
    if out.as_os_str().is_empty() {
        ".".to_owned()
    } else {
        out.display().to_string()
    }
}

/// `plan --help`: the command and the schemas of its results and errors.
fn help(run: &mut Run<'_>) {
    let emits: Vec<Value> = DESCRIBED
        .iter()
        .map(|(id, text)| {
            let version = schema_version(text);
            json!({"id": id, "version": version})
        })
        .collect();
    let mut effects = effects(&Arguments::default(), Path::new("."));
    effects["bookkeeping"] = run.bookkeeping();
    run.describe(
        json!({"event": "command", "name": "plan", "intent": INTENT, "effects": effects,
               "secrets": SECRETS, "emits": emits}),
        schemas::COMMAND,
    );
    for (id, text) in DESCRIBED {
        let schema: Value = serde_json::from_str(text).unwrap_or(Value::Null);
        run.describe(
            json!({"event": "schema", "id": id, "version": schema_version(text), "schema": schema}),
            schemas::SCHEMA,
        );
    }
}

/// The version a schema document pins in `_schema`.
fn schema_version(text: &str) -> String {
    serde_json::from_str::<Value>(text)
        .ok()
        .and_then(|doc| {
            doc["properties"]["_schema"]["properties"]["version"]["const"]
                .as_str()
                .map(str::to_owned)
        })
        .unwrap_or_default()
}

/// What `gh` or `git` reported, as an error line's fields.
struct Failure {
    code: &'static str,
    source: String,
    error: String,
    retryable: bool,
}

impl Failure {
    fn gh(error: &GhError) -> Self {
        let (source, text) = match error {
            GhError::CommandFailed { source, detail }
            | GhError::ResponseInvalid { source, detail } => (source.clone(), detail.clone()),
            GhError::ListLimitReached { source, limit } => (
                source.clone(),
                format!("the result filled --limit {limit}; possible truncation"),
            ),
        };
        Self {
            code: error.code(),
            source,
            error: text,
            retryable: matches!(error, GhError::CommandFailed { .. }),
        }
    }

    fn git(error: &GitError) -> Self {
        let source = match error {
            GitError::Spawn { command, .. }
            | GitError::Failed { command, .. }
            | GitError::Unreadable { command, .. } => command.clone(),
            GitError::NotARepository { .. } | GitError::NotTopLevel { .. } => {
                "git rev-parse".to_owned()
            }
            _ => "git".to_owned(),
        };
        Self {
            code: "git.command_failed",
            source: home_as_tilde(&source),
            error: home_as_tilde(&error.to_string()),
            retryable: true,
        }
    }

    fn report(&self, run: &mut Run<'_>) {
        let remedy = match self.code {
            "gh.command_failed" => {
                "check `gh auth status` and the network, then rerun; nothing was compiled from a partial read"
            }
            "gh.list_limit_reached" => {
                "narrow the seeds with --root; a list that fills its limit may be truncated (threat model C15)"
            }
            "gh.response_invalid" => {
                "report the gh version with the receipt; a malformed answer is not fixed by running again"
            }
            _ => "run the command shown in detail.source inside --repo to see why",
        };
        run.error(
            self.code,
            &one_sentence(&format!("{}: {}", self.source, self.error)),
            Some(remedy),
            Some(self.retryable),
            Some(json!({"source": self.source, "error": self.error, "phase": "discovery"})),
        );
    }
}

/// One line of at most 600 characters.
pub(crate) fn one_sentence(text: &str) -> String {
    let flat = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= 600 {
        flat
    } else {
        flat.chars().take(597).collect::<String>() + "..."
    }
}

/// The home directory written as `~`, as 1.x shows it.
pub(crate) fn home_as_tilde(text: &str) -> String {
    match std::env::var("HOME") {
        Ok(home) if !home.is_empty() && home != "/" => text.replace(&home, "~"),
        _ => text.to_owned(),
    }
}

/// The local and remote-tracking branch names of the repository `--repo`
/// is in, sorted and distinct.
fn branch_names(dir: &Path) -> Result<Vec<String>, GitError> {
    let repository = match GitRepository::open(dir) {
        Err(GitError::NotTopLevel { top_level, .. }) => GitRepository::open(top_level),
        other => other,
    }?;
    let names: BTreeSet<String> = repository
        .read_branches()?
        .into_iter()
        .map(|branch| branch.name)
        .filter(|name| !name.ends_with("/HEAD"))
        .collect();
    Ok(names.into_iter().collect())
}

/// Whether `name` holds `number` with no digit on either side, as 1.x
/// matches `(?<!\d)N(?!\d)`.
fn names_issue(name: &str, number: u32) -> bool {
    let number = number.to_string();
    name.match_indices(&number).any(|(at, _)| {
        let before = name[..at].chars().next_back();
        let after = name[at + number.len()..].chars().next();
        !before.is_some_and(|c| c.is_ascii_digit()) && !after.is_some_and(|c| c.is_ascii_digit())
    })
}

/// The teams a CODEOWNERS text names, in order of first appearance, as
/// 1.x lists them (`codeowners_teams_not_expanded`).
fn codeowners_teams(text: &str) -> Vec<String> {
    let mut teams: Vec<String> = Vec::new();
    for line in text.lines() {
        let before = line.split('#').next().unwrap_or_default();
        for token in before.split_whitespace().skip(1) {
            if let Some(name) = token.strip_prefix('@')
                && name.contains('/')
                && !teams.iter().any(|t| t == name)
            {
                teams.push(name.to_owned());
            }
        }
    }
    teams
}

/// The display input (decision D13): what the adapters read beside the
/// observations, only to show it.
pub(crate) fn display(
    shown: Shown,
    observations: &Observations,
    parameters: &Parameters,
    branches: &[String],
) -> Display {
    let mut display = Display {
        titles: shown.titles,
        urls: shown.urls,
        pull_request_urls: shown.pull_request_urls,
        ..Display::default()
    };
    let home = &parameters.home;
    for reference in observations.issues.keys() {
        if Repo::of(reference) == *home {
            let named: Vec<String> = branches
                .iter()
                .filter(|b| names_issue(b, reference.number()))
                .cloned()
                .collect();
            display
                .recoverable_branches
                .insert(reference.clone(), named);
        }
    }
    if parameters.trust.codeowners {
        for (repo, slot) in observations.codeowners.iter().flatten() {
            if let Observed::Value(Some(file)) = slot {
                display.codeowners.insert(
                    repo.to_string(),
                    codeowners_persons(&file.text).into_iter().collect(),
                );
                let teams = codeowners_teams(&file.text);
                if !teams.is_empty() {
                    display
                        .codeowners_teams_not_expanded
                        .insert(repo.to_string(), teams);
                }
            }
        }
    }
    display
}

/// What discovery read, by id and digest only (threat model C3), and the
/// declared input's bytes.
fn observed(run: &mut Run<'_>, observations: &Observations, display: &Display) {
    let digest = |text: Option<&str>| sha256::hex(text.unwrap_or_default().as_bytes());
    let items: Vec<Value> = observations
        .issues
        .iter()
        .filter_map(|(reference, slot)| match slot {
            Observed::Value(issue) => Some((reference, issue)),
            Observed::Unavailable(_) => None,
        })
        .map(|(reference, issue)| {
            let body = match observations.bodies.get(reference) {
                Some(Observed::Value(body)) => json!(digest(Some(&body.text))),
                _ => Value::Null,
            };
            json!({
                "id": reference.to_string(),
                "state": if issue.state == IssueState::Open { "open" } else { "closed" },
                "state_reason": issue.state_reason,
                "title_sha256": digest(display.titles.get(reference).map(String::as_str)),
                "body_sha256": body,
            })
        })
        .collect();
    run.step(
        &format!("observed {} issue(s)", items.len()),
        "issue bodies are declared inputs by digest and id; the input's digest is over this list (docs/topics/output); a body that was not read has a null digest",
        Some(json!({"issues": items})),
    );
    run.input(&parley::canonical(&Value::Array(items)));
}

/// The error lines a rendered plan's `error_codes` call for, after its
/// results.
fn plan_errors(run: &mut Run<'_>, lines: &[Value]) {
    let findings = |code: &str| -> Vec<&Value> {
        lines
            .iter()
            .filter(|l| l["event"] == "finding" && l["code"] == code)
            .map(|l| &l["subject"])
            .collect()
    };
    let Some(plan) = lines.first() else {
        return;
    };
    for code in plan["error_codes"].as_array().into_iter().flatten() {
        match code.as_str() {
            Some("graph.cycle") => run.error(
                "graph.cycle",
                "Cycle detected in hard structural edges",
                Some("split the shared foundation into a predecessor issue, or remove the edge that closes the cycle"),
                Some(false),
                Some(json!({"cyclic_nodes": findings("graph.cyclic_node")})),
            ),
            Some("graph.unresolved_prerequisites") => run.error(
                "graph.unresolved_prerequisites",
                "Unresolved prerequisites: unknown references and/or stale (merged) hints",
                Some("fix the references the prerequisite findings name"),
                Some(false),
                Some(json!({
                    "unknown": findings("prerequisite.unknown").len(),
                    "stale_merged_hints": findings("prerequisite.stale_merged_hint").len(),
                })),
            ),
            Some("frontmatter.invalid") => {
                let mut violating: Vec<IssueRef> = findings("frontmatter.violation")
                    .iter()
                    .filter_map(|s| s.as_str().and_then(IssueRef::parse))
                    .collect();
                violating.sort();
                violating.dedup();
                let ids: Vec<String> = violating.iter().map(ToString::to_string).collect();
                run.error(
                    "frontmatter.invalid",
                    &format!("{} issue(s) have invalid frontmatter", ids.len()),
                    Some("fix each frontmatter.violation finding; do not dispatch from this plan"),
                    Some(false),
                    Some(json!({"violating_issues": ids})),
                );
            }
            _ => {}
        }
    }
}

/// The run parameters of `plan`: the home repository, the roots, the read
/// scope, the trust and the capacities.
fn parameters(arguments: &Arguments, home: Repo) -> Parameters {
    let mut owners: BTreeSet<String> = arguments
        .trust_owners
        .iter()
        .map(|o| o.to_ascii_lowercase())
        .collect();
    owners.insert(home.owner().to_owned());
    Parameters {
        roots: arguments.roots.clone(),
        read_scope: ReadScope {
            owners,
            repositories: arguments
                .trust_repos
                .iter()
                .filter_map(|r| Repo::parse(r))
                .collect(),
        },
        trust: TrustParameters {
            policy: TRUST_POLICY.to_owned(),
            logins: arguments.trust.clone(),
            codeowners: arguments.trust_codeowners,
        },
        capacities: capacities(&arguments.capacities).unwrap_or_default(),
        home,
    }
}

/// Reads the backlog, plans it, and writes the result lines and errors.
fn plan_live(run: &mut Run<'_>, arguments: &Arguments, repo_dir: &Path) {
    let home = match repository_of("gh", &[], repo_dir) {
        Ok(home) => home,
        Err(error) => return Failure::gh(&error).report(run),
    };
    run.step(
        &format!("the home repository is {home}"),
        "gh resolves it from --repo; references compare in this lowercase spelling",
        None,
    );
    let branches = match branch_names(repo_dir) {
        Ok(branches) => branches,
        Err(error) => return Failure::git(&error).report(run),
    };
    run.step(
        &format!("listed {} branch(es)", branches.len()),
        "a branch whose name carries an issue number is recoverable work for that issue",
        None,
    );
    let parameters = parameters(arguments, home.clone());
    let forge = GhForge::new(home).current_dir(repo_dir);
    let outcome = plan(&parameters, &forge);
    let failures = forge.failures();
    let observations = forge.observations();
    if let Some(Observed::Value(pulls)) = &observations.home_open_pull_requests {
        run.step(
            &format!("listed {} open pull request(s)", pulls.len()),
            "a pull request marks a task in flight only from a same-repository branch by a trusted author (C4)",
            None,
        );
    }
    let display = display(forge.shown(), &observations, &parameters, &branches);
    if failures.is_empty() {
        observed(run, &observations, &display);
    }
    let outcome = match outcome {
        Ok(outcome) => outcome,
        Err(missing) => {
            // The gh forge records every slot it reads; a missing one is a defect.
            run.error(
                "plan.observation_missing",
                &format!("the planner read a slot the forge did not record: {missing}"),
                Some("report this defect with the receipt"),
                Some(false),
                None,
            );
            return;
        }
    };
    if arguments.capture_bundle() {
        replay::capture(run, &parameters, &observations);
    } else {
        record(run, &parameters, &outcome);
    }
    conclude(run, &parameters, &outcome, &failures, &display);
}

/// A reference that resolves to nothing, for the recorded cause (profile
/// rules D11 to D13), read from `source`. The reference is the cause's,
/// never one read out of the reason (flyingrobots/taskalisk#51). The
/// catalogued code `profile.D11` has an upper-case letter, which a
/// parley.error code may not, so the code is `issue.not_found` and the rule
/// is in the detail.
pub(crate) fn not_found(run: &mut Run<'_>, unavailable: &str, cause: &Cause, source: &str) {
    let reference = &cause.reference;
    let repo = Repo::of(reference);
    let problem = match cause.not_found {
        NotFound::Owner => format!(
            "{reference}: no account named {} was found",
            reference.owner()
        ),
        // OB17: GitHub answers a repository the token cannot see as one
        // that does not exist.
        NotFound::Repository => format!(
            "{reference}: the repository {repo} was not found; a private repository the token cannot see looks the same"
        ),
        NotFound::Number => format!(
            "{reference}: {repo} has no issue or pull request numbered {} that the token can see",
            reference.number()
        ),
    };
    run.error(
        "issue.not_found",
        &one_sentence(&problem),
        Some("fix the reference: its owner, repository or number names nothing gh can see"),
        Some(false),
        Some(json!({
            "rule": cause.not_found.label(),
            "not_found": cause.not_found.as_str(),
            "reference": reference.to_string(),
            "source": source,
            "error": unavailable,
            "phase": "discovery",
        })),
    );
}

/// The result lines of a plan and the errors its `error_codes` call for.
pub(crate) fn results(
    run: &mut Run<'_>,
    parameters: &Parameters,
    outcome: &Outcome,
    display: &Display,
) {
    match render::lines(parameters, outcome, Some(display)) {
        Ok(lines) => {
            for line in &lines {
                run.result(line.clone());
            }
            plan_errors(run, &lines);
        }
        Err(why) => run.error(
            "plan.not_rendered",
            &format!("the plan could not be rendered: {why:?}"),
            Some("report this defect with the receipt"),
            Some(false),
            None,
        ),
    }
}

/// The lines of an outcome: a plan's results and errors, or the errors of
/// a run that has no plan. A plan the core made while the gh adapter
/// recorded a failed read is not trusted: the failures are reported and no
/// plan is written (fail closed).
fn conclude(
    run: &mut Run<'_>,
    parameters: &Parameters,
    outcome: &Outcome,
    failures: &[GhError],
    display: &Display,
) {
    match outcome {
        Outcome::Invalid { .. } | Outcome::Planned { .. } if !failures.is_empty() => {
            for failure in failures {
                Failure::gh(failure).report(run);
            }
        }
        Outcome::Rejected(rejection) => reject(run, rejection),
        Outcome::Incomplete {
            unavailable,
            cause: Some(cause),
        } => {
            not_found(run, unavailable, cause, "gh");
            for failure in failures {
                Failure::gh(failure).report(run);
            }
        }
        Outcome::Incomplete {
            unavailable,
            cause: None,
        } => {
            if failures.is_empty() {
                run.error(
                    "gh.response_invalid",
                    &one_sentence(unavailable),
                    Some("report the gh version with the receipt; a malformed answer is not fixed by running again"),
                    Some(false),
                    Some(json!({"source": "gh", "error": unavailable, "phase": "discovery"})),
                );
            }
            for failure in failures {
                Failure::gh(failure).report(run);
            }
        }
        Outcome::Invalid { .. } | Outcome::Planned { .. } => {
            results(run, parameters, outcome, display);
        }
    }
}

/// The evaluation record of the run (flyingrobots/taskalisk#30), as a
/// receipt step: the formats, the profile, the evaluator, the discovery
/// scope and the result. Without `--capture-bundle` the bundle is not
/// retained, so its replay is unavailable; with it, the retained record is
/// written beside the receipt instead ([`replay::capture`]), because it
/// holds issue bodies, which a receipt never does.
fn record(run: &mut Run<'_>, parameters: &Parameters, outcome: &Outcome) {
    let record = unretained(
        parameters,
        outcome,
        &Evaluator {
            name: TOOL.to_owned(),
            version: VERSION.to_owned(),
        },
        "the observation bundle was not captured; plan --capture-bundle captures it (flyingrobots/taskalisk#59)",
    );
    let value: Value = serde_json::from_str(&record.to_json()).unwrap_or(Value::Null);
    run.step(
        "recorded the evaluation (taskalisk-evaluation/1)",
        "every plan emits an evaluation record naming the formats, the profile, the evaluator and what it planned from (decision 0001, section 5; flyingrobots/taskalisk#30)",
        Some(json!({"record": value})),
    );
}

pub(crate) fn reject(run: &mut Run<'_>, rejection: &Rejection) {
    let (code, problem, remedy) = match rejection {
        Rejection::RootOutsideScope(root) => (
            "root.out_of_scope",
            format!("--root {root} is outside the trusted repositories"),
            "add --trust-owner or --trust-repo for that repository, or choose a root inside the scope",
        ),
        Rejection::RootNotAReference(text) => (
            "root.invalid_reference",
            format!("--root {text:?} is not a reference"),
            "name the root as owner/repo#N",
        ),
        Rejection::UnknownPolicy(policy) => (
            "plan.unknown_policy",
            format!("the trust policy {policy:?} is not one this planner implements"),
            "report this defect with the receipt",
        ),
    };
    run.error(
        code,
        &problem,
        Some(remedy),
        Some(false),
        Some(json!({"source": "--root", "error": problem, "phase": "discovery"})),
    );
}

#[cfg(test)]
mod tests {
    use super::{capacities, codeowners_teams, command, conclude, names_issue, relative};
    use crate::parley::{Run, Start};
    use crate::render::Display;
    use issue_dag_core::{
        Cause, Graph, IssueRef, NotFound, Outcome, Parameters, ReadScope, Repo, TRUST_POLICY,
        TrustParameters,
    };
    use issue_dag_gh::GhError;
    use serde_json::json;
    use std::collections::{BTreeMap, BTreeSet};
    use std::path::Path;

    static NEXT: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

    /// The exit status, stdout and stderr of a run that concludes `outcome`
    /// after the gh adapter recorded `failures`.
    fn concluded(outcome: &Outcome, failures: &[GhError]) -> (u8, String, String) {
        let dir = std::env::temp_dir().join(format!(
            "taskalisk-conclude-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("a directory");
        let home = Repo::parse("o/r").expect("a repository");
        let parameters = Parameters {
            home,
            roots: Vec::new(),
            read_scope: ReadScope {
                owners: BTreeSet::from(["o".to_owned()]),
                repositories: BTreeSet::new(),
            },
            trust: TrustParameters {
                policy: TRUST_POLICY.to_owned(),
                logins: Vec::new(),
                codeowners: false,
            },
            capacities: BTreeMap::new(),
        };
        let (mut out, mut err) = (Vec::new(), Vec::new());
        let start = Start {
            tool: "taskalisk",
            v: "0",
            command: "plan",
            cwd: &dir,
            argv: Vec::new(),
            resolved: json!({}),
            inputs: Vec::new(),
            effects: json!({"reads": [], "writes": [], "network": true, "idempotent": true}),
            secrets: Vec::new(),
            secret_names: Vec::new(),
            human: None,
            retention: 50,
        };
        let mut run = Run::start(start, &mut out, &mut err).expect("a run");
        conclude(
            &mut run,
            &parameters,
            outcome,
            failures,
            &Display::default(),
        );
        let status = run.end();
        let _ = std::fs::remove_dir_all(&dir);
        (
            status,
            String::from_utf8(out).expect("UTF-8"),
            String::from_utf8(err).expect("UTF-8"),
        )
    }

    /// Every line of a stream validates against the exact schema it names,
    /// by the vendored writer's checker (`tests/validate_lines.py`).
    fn assert_valid(stream: &str) {
        use std::io::Write as _;
        let tests = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests");
        let mut child = std::process::Command::new("python3")
            .current_dir(tests)
            .arg("validate_lines.py")
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .spawn()
            .expect("python3 runs");
        child
            .stdin
            .as_mut()
            .expect("stdin")
            .write_all(stream.as_bytes())
            .expect("the lines are written");
        let out = child.wait_with_output().expect("the validator ends");
        assert!(
            out.status.success(),
            "lines do not validate:\n{}",
            String::from_utf8_lossy(&out.stdout)
        );
    }

    /// The `parley.error` lines of a stream.
    fn errors(stream: &str) -> Vec<serde_json::Value> {
        stream
            .lines()
            .map(|l| serde_json::from_str::<serde_json::Value>(l).expect("JSON"))
            .filter(|l| l["_schema"]["id"] == "parley.error")
            .collect()
    }

    #[test]
    fn an_incomplete_run_with_a_cause_reports_issue_not_found_with_its_rule() {
        for (cause, rule) in [
            (NotFound::Owner, "D11"),
            (NotFound::Repository, "D12"),
            (NotFound::Number, "D13"),
        ] {
            // The reason names another reference: the one reported is the
            // cause's, never one parsed out of the reason (#51).
            let incomplete = Outcome::Incomplete {
                unavailable: "o/r#1 resolves to no issue gh can see (HTTP 404)".to_owned(),
                cause: Some(Cause {
                    not_found: cause,
                    reference: IssueRef::parse("o/r#9").expect("a reference"),
                }),
            };
            let (status, _, err) = concluded(&incomplete, &[]);
            assert_eq!(status, 2, "{err}");
            assert_valid(&err);
            let errors = errors(&err);
            assert_eq!(errors.len(), 1, "{err}");
            assert_eq!(errors[0]["code"], "issue.not_found", "{err}");
            assert_eq!(errors[0]["detail"]["rule"], rule, "{err}");
            assert_eq!(errors[0]["detail"]["not_found"], cause.as_str(), "{err}");
            assert_eq!(errors[0]["detail"]["reference"], "o/r#9", "{err}");
            let message = errors[0]["problem"].as_str().expect("a problem");
            assert!(message.contains("o/r#9"), "{message}");
            // D12: a private repository the token cannot see answers as one
            // that does not exist, and the message says so.
            assert_eq!(
                message.contains("private repository"),
                cause == NotFound::Repository,
                "{message}"
            );
        }
        // Without a cause, an unavailable read the adapter did not record is
        // a malformed answer.
        let incomplete = Outcome::Incomplete {
            unavailable: "truncated".to_owned(),
            cause: None,
        };
        let (status, _, err) = concluded(&incomplete, &[]);
        assert_eq!(status, 2);
        assert_eq!(errors(&err)[0]["code"], "gh.response_invalid", "{err}");
    }

    #[test]
    fn a_plan_made_while_a_read_failed_is_an_error_not_a_plan() {
        let planned = Outcome::Planned {
            findings: BTreeSet::new(),
            graph: Graph::default(),
        };
        let (status, out, _) = concluded(&planned, &[]);
        assert_eq!(status, 0, "{out}");
        assert!(out.contains("\"taskalisk.plan\""), "{out}");
        let failed = GhError::CommandFailed {
            source: "gh api x".to_owned(),
            detail: "boom".to_owned(),
        };
        let (status, out, _) = concluded(&planned, &[failed]);
        assert_eq!(status, 2, "{out}");
        assert!(
            !out.contains("\"taskalisk.plan\""),
            "no plan from a failed read: {out}"
        );
    }

    fn strings(items: &[&str]) -> Vec<String> {
        items.iter().map(|s| (*s).to_owned()).collect()
    }

    #[test]
    fn a_branch_names_an_issue_by_its_whole_number() {
        assert!(names_issue("task/2-home-two", 2));
        assert!(names_issue("2", 2));
        assert!(!names_issue("task/22-other", 2));
        assert!(!names_issue("v12", 2));
    }

    #[test]
    fn the_command_is_named_found_or_inferred_as_in_1x() {
        assert_eq!(
            command(&strings(&["plan", "--repo", "x"])).0.as_deref(),
            Some("plan")
        );
        let (name, rest, inferred) = command(&strings(&["--repo", "plan", "edit"]));
        assert_eq!((name.as_deref(), inferred), (Some("edit"), false));
        assert_eq!(rest, strings(&["--repo", "plan"]));
        assert_eq!(
            command(&strings(&["--from-github"])).0.as_deref(),
            Some("plan")
        );
        assert!(command(&strings(&["--from-github"])).2);
        assert_eq!(command(&strings(&[])).0.as_deref(), Some("inventory"));
        assert_eq!(command(&strings(&["--help"])).0, None);
    }

    #[test]
    fn a_capacity_is_a_name_and_a_positive_integer() {
        assert!(capacities(&strings(&["gpu=2"])).is_some_and(|c| c["gpu"] == 2));
        for bad in ["gpu", "gpu=0", "=1", "gpu=-1", "gpu=x", "gpu="] {
            assert_eq!(capacities(&strings(&[bad])), None, "{bad}");
        }
    }

    #[test]
    fn teams_are_listed_once_in_order() {
        let text = "* @o @org/b # @org/c\ndocs/ @org/a @org/b\n";
        assert_eq!(codeowners_teams(text), strings(&["org/b", "org/a"]));
    }

    #[test]
    fn a_path_is_shown_relative_to_the_working_directory() {
        assert_eq!(relative(Path::new("/a/b/c"), Path::new("/a/b")), "c");
        assert_eq!(relative(Path::new("/a/x"), Path::new("/a/b")), "../x");
        assert_eq!(relative(Path::new("/a"), Path::new("/a")), ".");
    }
}
