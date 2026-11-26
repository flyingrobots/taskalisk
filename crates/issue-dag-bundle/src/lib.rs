//! Reads an observation bundle, `issue-dag-observations/1`
//! (`tests/fixtures/issue-dag/corpus/bundle.md`), into the domain values of
//! `issue-dag-core`, and rejects a bundle that breaks rules OB1 to OB13.
//!
//! This crate holds the JSON; the core stays free of it. A slot the bundle
//! does not hold is left unrecorded, so that a run that needs it fails with
//! [`issue_dag_core::Missing`] (OB5) instead of reading it as empty.

use core::fmt;
use std::collections::{BTreeMap, BTreeSet};

use issue_dag_core::{
    Actor, Body, Bundle, CodeownersFile, Issue, IssueRef, IssueState, Observations, Observed,
    Parameters, PullRequest, ReadScope, Repo, TrustParameters,
};
use serde_json::{Map, Value};

/// The bundle version this reader reads (OB1).
pub const BUNDLE_VERSION: &str = "issue-dag-observations/1";
/// The format a bundle names (OB2).
pub const FORMAT: &str = "issue-dag/2";
/// The planning profile a bundle names (OB2).
pub const PROFILE: &str = "issue-dag-planning/2";
/// Where a CODEOWNERS file may be found (OB11).
pub const CODEOWNERS_PATHS: [&str; 3] = [".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"];

/// Why a bundle was rejected: where in it, and what is wrong.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BundleError {
    /// A path into the bundle, such as `observations.issues["o/r#1"]`.
    pub at: String,
    /// What is wrong there.
    pub problem: String,
}

impl fmt::Display for BundleError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.at, self.problem)
    }
}

impl std::error::Error for BundleError {}

type Read<T> = Result<T, BundleError>;

fn fail<T>(at: &str, problem: impl Into<String>) -> Read<T> {
    Err(BundleError {
        at: at.to_owned(),
        problem: problem.into(),
    })
}

/// Reads a bundle from its JSON text.
///
/// # Errors
///
/// [`BundleError`] when the text is not JSON or breaks a bundle rule.
pub fn load(text: &str) -> Read<Bundle> {
    let value: Value = match serde_json::from_str(text) {
        Ok(v) => v,
        Err(e) => return fail("bundle", format!("not JSON: {e}")),
    };
    let top = exact(
        &value,
        "bundle",
        &["bundle", "format", "profile", "parameters", "observations"],
        &[],
    )?;
    expect_text(&top["bundle"], "bundle", BUNDLE_VERSION)?;
    expect_text(&top["format"], "format", FORMAT)?;
    expect_text(&top["profile"], "profile", PROFILE)?;
    let parameters = parameters(&top["parameters"])?;
    let observations = observations(&top["observations"], &parameters)?;
    Ok(Bundle {
        parameters,
        observations,
    })
}

/// An object with every member of `required`, some of `optional`, and no
/// other.
fn exact<'a>(
    value: &'a Value,
    at: &str,
    required: &[&str],
    optional: &[&str],
) -> Read<&'a Map<String, Value>> {
    let Some(object) = value.as_object() else {
        return fail(at, "not an object");
    };
    for member in required {
        if !object.contains_key(*member) {
            return fail(at, format!("lacks the member {member:?}"));
        }
    }
    for key in object.keys() {
        if !required.contains(&key.as_str()) && !optional.contains(&key.as_str()) {
            return fail(at, format!("has the member {key:?}, which is not defined"));
        }
    }
    Ok(object)
}

fn expect_text(value: &Value, at: &str, want: &str) -> Read<()> {
    if value.as_str() == Some(want) {
        Ok(())
    } else {
        fail(at, format!("must be {want:?}"))
    }
}

fn text<'a>(value: &'a Value, at: &str) -> Read<&'a str> {
    value.as_str().map_or_else(|| fail(at, "not a string"), Ok)
}

fn boolean(value: &Value, at: &str) -> Read<bool> {
    value
        .as_bool()
        .map_or_else(|| fail(at, "not a boolean"), Ok)
}

fn list<'a>(value: &'a Value, at: &str) -> Read<&'a Vec<Value>> {
    value.as_array().map_or_else(|| fail(at, "not a list"), Ok)
}

fn optional(value: &Value) -> Option<&Value> {
    (!value.is_null()).then_some(value)
}

/// A repository in canonical form (OB13).
fn repo(value: &Value, at: &str) -> Read<Repo> {
    let raw = text(value, at)?;
    match Repo::parse(raw) {
        Some(r) if r.to_string() == raw => Ok(r),
        Some(_) => fail(at, format!("{raw:?} is not in canonical form")),
        None => fail(at, format!("{raw:?} is not owner/repo")),
    }
}

/// A reference in canonical form (OB13).
fn reference(raw: &str, at: &str) -> Read<IssueRef> {
    match IssueRef::parse(raw) {
        Some(r) if r.to_string() == raw => Ok(r),
        Some(_) => fail(at, format!("{raw:?} is not in canonical form")),
        None => fail(at, format!("{raw:?} is not a reference")),
    }
}

fn references(value: &Value, at: &str) -> Read<Vec<IssueRef>> {
    list(value, at)?
        .iter()
        .enumerate()
        .map(|(i, item)| {
            let at = format!("{at}[{i}]");
            reference(text(item, &at)?, &at)
        })
        .collect()
}

fn parameters(value: &Value) -> Read<Parameters> {
    let at = "parameters";
    let p = exact(
        value,
        at,
        &["home", "roots", "read_scope", "trust", "capacities"],
        &[],
    )?;
    let home = repo(&p["home"], "parameters.home")?;
    let roots = list(&p["roots"], "parameters.roots")?
        .iter()
        .enumerate()
        .map(|(i, r)| text(r, &format!("parameters.roots[{i}]")).map(str::to_owned))
        .collect::<Read<Vec<String>>>()?;

    let scope_at = "parameters.read_scope";
    let s = exact(&p["read_scope"], scope_at, &["owners", "repositories"], &[])?;
    let mut owners = BTreeSet::new();
    for (i, owner) in list(&s["owners"], scope_at)?.iter().enumerate() {
        let at = format!("{scope_at}.owners[{i}]");
        let raw = text(owner, &at)?;
        if raw.is_empty() || raw != raw.to_ascii_lowercase() || raw.contains('/') {
            return fail(&at, format!("{raw:?} is not an owner in canonical form"));
        }
        owners.insert(raw.to_owned());
    }
    let repositories = list(&s["repositories"], scope_at)?
        .iter()
        .enumerate()
        .map(|(i, r)| repo(r, &format!("{scope_at}.repositories[{i}]")))
        .collect::<Read<BTreeSet<Repo>>>()?;
    let read_scope = ReadScope {
        owners,
        repositories,
    };
    if !read_scope.contains(&home) {
        return fail(scope_at, "does not include the home repository");
    }

    let trust_at = "parameters.trust";
    let t = exact(
        &p["trust"],
        trust_at,
        &["policy", "logins", "codeowners"],
        &[],
    )?;
    let trust = TrustParameters {
        policy: text(&t["policy"], "parameters.trust.policy")?.to_owned(),
        logins: list(&t["logins"], "parameters.trust.logins")?
            .iter()
            .enumerate()
            .map(|(i, l)| text(l, &format!("parameters.trust.logins[{i}]")).map(str::to_owned))
            .collect::<Read<Vec<String>>>()?,
        codeowners: boolean(&t["codeowners"], "parameters.trust.codeowners")?,
    };

    let Some(caps) = p["capacities"].as_object() else {
        return fail("parameters.capacities", "not an object");
    };
    let mut capacities = BTreeMap::new();
    for (name, n) in caps {
        match n.as_u64() {
            Some(n) if n > 0 => {
                capacities.insert(name.clone(), n);
            }
            _ => {
                return fail(
                    &format!("parameters.capacities[{name:?}]"),
                    "not a positive integer",
                );
            }
        }
    }
    Ok(Parameters {
        home,
        roots,
        read_scope,
        trust,
        capacities,
    })
}

/// A slot (OB4): exactly one of `value` and `unavailable`, the latter a
/// non-empty string.
fn slot<T>(
    value: &Value,
    at: &str,
    read: impl FnOnce(&Value, &str) -> Read<T>,
) -> Read<Observed<T>> {
    let Some(object) = value.as_object() else {
        return fail(at, "a slot must be an object");
    };
    if object.len() != 1 {
        return fail(at, "a slot has exactly one member, value or unavailable");
    }
    if let Some(v) = object.get("value") {
        return read(v, &format!("{at}.value")).map(Observed::Value);
    }
    match object.get("unavailable").and_then(Value::as_str) {
        Some(why) if !why.is_empty() => Ok(Observed::Unavailable(why.to_owned())),
        Some(_) => fail(at, "an unavailable slot needs a reason"),
        None => fail(at, "a slot has exactly one member, value or unavailable"),
    }
}

fn observations(value: &Value, parameters: &Parameters) -> Read<Observations> {
    let at = "observations";
    // The members bundle section 2 defines. Anything else is refused rather
    // than ignored, so that a misspelt slot cannot pass unnoticed.
    let o = exact(
        value,
        at,
        &[],
        &[
            "home_open_issues",
            "home_open_pull_requests",
            "issues",
            "permissions",
            "codeowners",
        ],
    )?;
    let home_open_issues = match o.get("home_open_issues") {
        None => None,
        Some(_) if !parameters.roots.is_empty() => {
            return fail(
                "observations.home_open_issues",
                "is absent when the run has roots (OB6)",
            );
        }
        Some(v) => Some(slot(v, "observations.home_open_issues", |v, at| {
            let refs = references(v, at)?;
            let distinct: BTreeSet<&IssueRef> = refs.iter().collect();
            if distinct.len() != refs.len() {
                return fail(at, "lists an issue twice");
            }
            if let Some(r) = refs.iter().find(|r| Repo::of(r) != parameters.home) {
                return fail(at, format!("{r} is not an issue of the home repository"));
            }
            Ok(refs)
        })?),
    };
    let home_open_pull_requests = o
        .get("home_open_pull_requests")
        .map(|v| {
            slot(v, "observations.home_open_pull_requests", |v, at| {
                list(v, at)?
                    .iter()
                    .enumerate()
                    .map(|(i, p)| pull_request(p, &format!("{at}[{i}]"), &parameters.home))
                    .collect()
            })
        })
        .transpose()?;

    let issues = o
        .get("issues")
        .map_or_else(|| Ok(BTreeMap::new()), |v| issues(v, parameters))?;
    let permissions = o
        .get("permissions")
        .map_or_else(|| Ok(BTreeMap::new()), permissions)?;
    let codeowners = match (o.get("codeowners"), parameters.trust.codeowners) {
        (None, _) => None,
        (Some(_), false) => {
            return fail(
                "observations.codeowners",
                "is absent when the policy reads no CODEOWNERS (OB11)",
            );
        }
        (Some(v), true) => Some(codeowners(v)?),
    };
    Ok(Observations {
        home_open_issues,
        home_open_pull_requests,
        issues,
        permissions,
        codeowners,
    })
}

/// OB8: issues keyed by a reference in canonical form, in the read scope.
fn issues(value: &Value, parameters: &Parameters) -> Read<BTreeMap<IssueRef, Observed<Issue>>> {
    let Some(map) = value.as_object() else {
        return fail("observations.issues", "not an object");
    };
    let mut issues = BTreeMap::new();
    for (key, s) in map {
        let at = format!("observations.issues[{key:?}]");
        let r = reference(key, &at)?;
        if !parameters.read_scope.contains(&Repo::of(&r)) {
            return fail(&at, "is outside the read scope and is never read (OB8)");
        }
        issues.insert(r, slot(s, &at, issue)?);
    }
    Ok(issues)
}

type Permissions = BTreeMap<Repo, BTreeMap<String, Observed<Option<String>>>>;

/// OB10: repository, then login in lower case, to a permission or null.
fn permissions(value: &Value) -> Read<Permissions> {
    let Some(map) = value.as_object() else {
        return fail("observations.permissions", "not an object");
    };
    let mut permissions = BTreeMap::new();
    for (repo_key, table) in map {
        let at = format!("observations.permissions[{repo_key:?}]");
        let r = repo(&Value::String(repo_key.clone()), &at)?;
        let Some(table) = table.as_object() else {
            return fail(&at, "not an object");
        };
        let mut logins = BTreeMap::new();
        for (login, s) in table {
            let at = format!("{at}[{login:?}]");
            if login.is_empty() || *login != login.to_ascii_lowercase() {
                return fail(&at, "a login is recorded in lower case (OB10)");
            }
            let level = slot(s, &at, |v, at| match v {
                Value::Null => Ok(None),
                Value::String(s) => Ok(Some(s.clone())),
                _ => fail(at, "a permission is a string or null"),
            })?;
            logins.insert(login.clone(), level);
        }
        permissions.insert(r, logins);
    }
    Ok(permissions)
}

/// OB11: repository to its CODEOWNERS file, or null.
fn codeowners(value: &Value) -> Read<BTreeMap<Repo, Observed<Option<CodeownersFile>>>> {
    let Some(map) = value.as_object() else {
        return fail("observations.codeowners", "not an object");
    };
    let mut files = BTreeMap::new();
    for (repo_key, s) in map {
        let at = format!("observations.codeowners[{repo_key:?}]");
        let r = repo(&Value::String(repo_key.clone()), &at)?;
        files.insert(r, slot(s, &at, codeowners_file)?);
    }
    Ok(files)
}

fn actor(value: &Value, at: &str) -> Read<Option<Actor>> {
    if value.is_null() {
        return Ok(None);
    }
    let a = exact(value, at, &["login", "type"], &[])?;
    Ok(Some(Actor {
        login: text(&a["login"], &format!("{at}.login"))?.to_owned(),
        actor_type: text(&a["type"], &format!("{at}.type"))?.to_owned(),
    }))
}

fn pull_request(value: &Value, at: &str, home: &Repo) -> Read<PullRequest> {
    let p = exact(
        value,
        at,
        &[
            "number",
            "repository",
            "head_repository",
            "cross_repository",
            "author",
            "draft",
            "closes",
        ],
        &[],
    )?;
    let Some(number) = p["number"].as_u64().filter(|n| *n > 0) else {
        return fail(&format!("{at}.number"), "not a positive integer");
    };
    let repository = repo(&p["repository"], &format!("{at}.repository"))?;
    if repository != *home {
        return fail(&format!("{at}.repository"), "is not the home repository");
    }
    let head_repository = optional(&p["head_repository"])
        .map(|v| repo(v, &format!("{at}.head_repository")))
        .transpose()?;
    let cross_repository = optional(&p["cross_repository"])
        .map(|v| boolean(v, &format!("{at}.cross_repository")))
        .transpose()?;
    Ok(PullRequest {
        number,
        repository,
        head_repository,
        cross_repository,
        author: actor(&p["author"], &format!("{at}.author"))?,
        draft: draft(&p["draft"], &format!("{at}.draft"))?,
        closes: references(&p["closes"], &format!("{at}.closes"))?,
    })
}

/// OB7: a draft flag is a boolean, or an unavailable slot when the flag
/// observed was not a boolean.
fn draft(value: &Value, at: &str) -> Read<Observed<bool>> {
    if let Some(flag) = value.as_bool() {
        return Ok(Observed::Value(flag));
    }
    if value.get("value").is_some() {
        return fail(at, "a draft flag is a boolean or an unavailable slot");
    }
    slot(value, at, boolean)
}

fn issue(value: &Value, at: &str) -> Read<Issue> {
    let i = exact(
        value,
        at,
        &[
            "address",
            "pull_request",
            "state",
            "state_reason",
            "author",
            "author_association",
            "body",
        ],
        &[],
    )?;
    let address = reference(
        text(&i["address"], &format!("{at}.address"))?,
        &format!("{at}.address"),
    )?;
    let state = match i["state"].as_str() {
        Some("open") => IssueState::Open,
        Some("closed") => IssueState::Closed,
        _ => return fail(&format!("{at}.state"), "must be open or closed"),
    };
    let text_or_null = |v: &Value, at: &str| {
        optional(v)
            .map(|v| text(v, at).map(str::to_owned))
            .transpose()
    };
    Ok(Issue {
        address,
        pull_request: boolean(&i["pull_request"], &format!("{at}.pull_request"))?,
        state,
        state_reason: text_or_null(&i["state_reason"], &format!("{at}.state_reason"))?,
        author: actor(&i["author"], &format!("{at}.author"))?,
        author_association: text_or_null(
            &i["author_association"],
            &format!("{at}.author_association"),
        )?,
        body: slot(&i["body"], &format!("{at}.body"), body)?,
    })
}

fn body(value: &Value, at: &str) -> Read<Body> {
    let b = exact(value, at, &["text", "editors"], &[])?;
    Ok(Body {
        text: text(&b["text"], &format!("{at}.text"))?.to_owned(),
        editors: list(&b["editors"], &format!("{at}.editors"))?
            .iter()
            .enumerate()
            .map(|(n, e)| actor(e, &format!("{at}.editors[{n}]")))
            .collect::<Read<Vec<Option<Actor>>>>()?,
    })
}

fn codeowners_file(value: &Value, at: &str) -> Read<Option<CodeownersFile>> {
    if value.is_null() {
        return Ok(None);
    }
    let c = exact(value, at, &["path", "text"], &[])?;
    let path = text(&c["path"], &format!("{at}.path"))?;
    if !CODEOWNERS_PATHS.contains(&path) {
        return fail(
            &format!("{at}.path"),
            format!("{path:?} is not a CODEOWNERS path"),
        );
    }
    Ok(Some(CodeownersFile {
        path: path.to_owned(),
        text: text(&c["text"], &format!("{at}.text"))?.to_owned(),
    }))
}
