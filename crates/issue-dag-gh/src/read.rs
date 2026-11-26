//! Each read: the `gh` invocation and the reading of its answer. A wrong
//! shape is an error, never a default.

use std::collections::BTreeSet;

use issue_dag_core::{
    Actor, Body, CodeownersFile, Issue, IssueRef, IssueState, Observed, PullRequest, Repo,
};
use serde_json::{Map, Value};

use crate::Limits;
use crate::error::GhError;
use crate::run::{Refusal, Runner};

/// The body and the actor of every body edit, the first edit being the
/// creation, in one query, so the editors are those of the body read. The
/// Python compiler's `EDIT_HISTORY_QUERY`, byte for byte.
pub const EDIT_HISTORY_QUERY: &str = "query($owner:String!,$name:String!,$number:Int!,$after:String){repository(owner:$owner,name:$name){issue(number:$number){body userContentEdits(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{editor{login __typename}}}}}}";

/// Where CODEOWNERS is looked for, in order (bundle rule OB11).
pub const CODEOWNERS_PATHS: [&str; 3] = [".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"];

/// The fields `gh pr list` is asked for.
const PULL_REQUEST_FIELDS: &str = "number,isDraft,closingIssuesReferences,author,isCrossRepository";

fn args(items: &[&str]) -> Vec<String> {
    items.iter().map(|item| (*item).to_owned()).collect()
}

fn json(source: &str, bytes: &[u8]) -> Result<Value, GhError> {
    serde_json::from_slice(bytes)
        .map_err(|error| GhError::invalid(source, format!("unparseable JSON output: {error}")))
}

fn object<'v>(
    source: &str,
    value: &'v Value,
    what: &str,
) -> Result<&'v Map<String, Value>, GhError> {
    value
        .as_object()
        .ok_or_else(|| GhError::invalid(source, format!("expected {what} to be a JSON object")))
}

/// A member that is absent or null is `None`; any other non-string is an
/// error.
fn optional_text(
    source: &str,
    item: &Map<String, Value>,
    key: &str,
) -> Result<Option<String>, GhError> {
    match item.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(text)) => Ok(Some(text.clone())),
        Some(_) => Err(GhError::invalid(source, format!("{key} is not a string"))),
    }
}

fn text(source: &str, item: &Map<String, Value>, key: &str) -> Result<String, GhError> {
    optional_text(source, item, key)?
        .ok_or_else(|| GhError::invalid(source, format!("{key} is missing")))
}

fn reference(source: &str, repo: &Repo, item: &Map<String, Value>) -> Result<IssueRef, GhError> {
    let number = item
        .get("number")
        .and_then(Value::as_u64)
        .ok_or_else(|| GhError::invalid(source, "an item has no integer number"))?;
    IssueRef::parse(&format!("{repo}#{number}"))
        .ok_or_else(|| GhError::invalid(source, format!("{repo}#{number} is not a reference")))
}

/// The open issues of `home` that are not pull requests (bundle rule OB6).
pub fn home_open_issues(
    runner: &Runner,
    home: &Repo,
    limits: Limits,
) -> Result<Vec<IssueRef>, GhError> {
    let path = format!(
        "repos/{}/{}/issues?state=open&per_page=100",
        home.owner(),
        home.name()
    );
    let source = format!("gh api {path}");
    let out = runner.run_strict(&source, &args(&["api", "--paginate", &path]))?;
    // `--paginate` writes one JSON array per page, one after another.
    let mut pages = 0;
    let mut issues = Vec::new();
    let mut seen = BTreeSet::new();
    for page in serde_json::Deserializer::from_slice(&out).into_iter::<Value>() {
        let page =
            page.map_err(|error| GhError::invalid(&source, format!("unparseable JSON: {error}")))?;
        let items = page
            .as_array()
            .ok_or_else(|| GhError::invalid(&source, "expected a JSON array page"))?;
        pages += 1;
        for item in items {
            let item = object(&source, item, "an issue")?;
            if item.get("pull_request").is_some_and(|pr| !pr.is_null()) {
                continue;
            }
            let listed = reference(&source, home, item)?;
            // Pages shifted under a concurrent change: an issue seen twice
            // means another may have been missed (bundle rule OB6).
            if !seen.insert(listed.clone()) {
                return Err(GhError::invalid(
                    &source,
                    format!("{listed} was listed twice; the pages shifted while they were read"),
                ));
            }
            issues.push(listed);
        }
    }
    if pages == 0 {
        return Err(GhError::invalid(&source, "no page was returned"));
    }
    if issues.len() >= limits.issues {
        return Err(GhError::ListLimitReached {
            source,
            limit: limits.issues,
        });
    }
    Ok(issues)
}

/// The open pull requests of `home` (bundle rule OB7).
pub fn home_open_pull_requests(
    runner: &Runner,
    home: &Repo,
    limits: Limits,
) -> Result<Vec<PullRequest>, GhError> {
    let source = "gh pr list";
    let limit = limits.pull_requests.to_string();
    let out = runner.run_strict(
        source,
        &args(&[
            "pr",
            "list",
            "--repo",
            &home.to_string(),
            "--state",
            "open",
            "--limit",
            &limit,
            "--json",
            PULL_REQUEST_FIELDS,
        ]),
    )?;
    let list = json(source, &out)?;
    let items = list
        .as_array()
        .ok_or_else(|| GhError::invalid(source, "expected a JSON array"))?;
    if items.len() >= limits.pull_requests {
        return Err(GhError::ListLimitReached {
            source: source.to_owned(),
            limit: limits.pull_requests,
        });
    }
    items
        .iter()
        .map(|item| pull_request(source, home, object(source, item, "a pull request")?))
        .collect()
}

fn pull_request(
    source: &str,
    home: &Repo,
    item: &Map<String, Value>,
) -> Result<PullRequest, GhError> {
    let number = item
        .get("number")
        .and_then(Value::as_u64)
        .ok_or_else(|| GhError::invalid(source, "a pull request has no integer number"))?;
    let draft = match item.get("isDraft") {
        Some(Value::Bool(draft)) => Observed::Value(*draft),
        // A draft flag that is not a boolean is unavailable (profile rule I5).
        _ => Observed::Unavailable(format!("pull request {number} has no boolean isDraft")),
    };
    let cross_repository = match item.get("isCrossRepository") {
        None | Some(Value::Null) => None,
        Some(Value::Bool(cross)) => Some(*cross),
        Some(_) => {
            return Err(GhError::invalid(
                source,
                format!("pull request {number} has a non-boolean isCrossRepository"),
            ));
        }
    };
    let author = match item.get("author") {
        None | Some(Value::Null) => None,
        Some(author) => {
            let author = object(source, author, "an author")?;
            let bot = match author.get("is_bot") {
                None | Some(Value::Null) => false,
                Some(Value::Bool(bot)) => *bot,
                Some(_) => return Err(GhError::invalid(source, "is_bot is not a boolean")),
            };
            Some(Actor {
                login: text(source, author, "login")?,
                actor_type: if bot { "Bot" } else { "User" }.to_owned(),
            })
        }
    };
    let references = item
        .get("closingIssuesReferences")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            GhError::invalid(
                source,
                format!("pull request {number} has no closingIssuesReferences list"),
            )
        })?;
    let closes = references
        .iter()
        .map(|closed| {
            let closed = object(source, closed, "a closing reference")?;
            let repo = match closed.get("repository") {
                // The Python compiler's default: the home repository.
                None | Some(Value::Null) => home.clone(),
                Some(repository) => {
                    let repository = object(source, repository, "a repository")?;
                    let owner = repository
                        .get("owner")
                        .and_then(Value::as_object)
                        .ok_or_else(|| GhError::invalid(source, "a repository has no owner"))?;
                    let spelled = format!(
                        "{}/{}",
                        text(source, owner, "login")?,
                        text(source, repository, "name")?
                    );
                    // The server's text is left out of the reason.
                    Repo::parse(&spelled).ok_or_else(|| {
                        GhError::invalid(
                            source,
                            format!(
                                "pull request {number} closes an issue in a repository whose name is not one"
                            ),
                        )
                    })?
                }
            };
            reference(source, &repo, closed)
        })
        .collect::<Result<_, _>>()?;
    Ok(PullRequest {
        number,
        repository: home.clone(),
        head_repository: None,
        cross_repository,
        author,
        draft,
        closes,
    })
}

/// The repository a REST issue's `repository_url` names, as
/// `.../repos/<owner>/<name>`.
fn repository_of(url: &str) -> Option<Repo> {
    let mut parts = url.trim_end_matches('/').rsplit('/');
    let name = parts.next()?;
    let owner = parts.next()?;
    (parts.next()? == "repos")
        .then(|| Repo::parse(&format!("{owner}/{name}")))
        .flatten()
}

/// What a reference resolves to (bundle rule OB8), without its body: the
/// REST issue alone, so that an issue a stranger wrote costs no further
/// query (threat model C15).
pub fn issue(runner: &Runner, reference: &IssueRef) -> Result<Observed<Issue>, GhError> {
    let path = format!(
        "repos/{}/{}/issues/{}",
        reference.owner(),
        reference.repo(),
        reference.number()
    );
    let source = format!("gh api {path}");
    let out = match runner.run(&source, &args(&["api", &path])) {
        Ok(out) => out,
        // Profile rule D10: a reference that resolves to nothing visible.
        Err(Refusal::NotFound) => {
            return Ok(Observed::Unavailable(format!(
                "{reference} resolves to no issue gh can see (HTTP 404)"
            )));
        }
        Err(Refusal::Failed(error)) => return Err(error),
    };
    let value = json(&source, &out)?;
    let item = object(&source, &value, "the issue")?;
    let url = text(&source, item, "repository_url")?;
    let repo = repository_of(&url)
        .ok_or_else(|| GhError::invalid(&source, "the issue has no parseable repository_url"))?;
    let address = self::reference(&source, &repo, item)?;
    let pull_request = item.get("pull_request").is_some_and(|pr| !pr.is_null());
    let state = match text(&source, item, "state")?.to_ascii_lowercase().as_str() {
        "open" => IssueState::Open,
        "closed" => IssueState::Closed,
        // The server's text is left out of the reason.
        _ => {
            return Err(GhError::invalid(
                &source,
                "the issue's state is neither open nor closed",
            ));
        }
    };
    let author = match item.get("user") {
        None | Some(Value::Null) => None,
        Some(user) => {
            let user = object(&source, user, "the user")?;
            Some(Actor {
                login: text(&source, user, "login")?,
                actor_type: text(&source, user, "type")?,
            })
        }
    };
    Ok(Observed::Value(Issue {
        address,
        pull_request,
        state,
        state_reason: optional_text(&source, item, "state_reason")?,
        author,
        author_association: optional_text(&source, item, "author_association")?,
        body: None,
    }))
}

/// Why the body of an issue already read is not read: it is a pull request,
/// or it was transferred (its address may be outside the read scope).
pub fn body_not_read(reference: &IssueRef, issue: &Issue) -> Option<String> {
    if issue.pull_request {
        Some(format!(
            "{reference} is a pull request; its body is not read"
        ))
    } else if issue.address == *reference {
        None
    } else {
        Some(format!(
            "{reference} was transferred to {}; its body is not read",
            issue.address
        ))
    }
}

/// The body and every body editor, every page read (the Python compiler's
/// `gh_issue_edit_history`): a page that claims another without a cursor,
/// a repeated cursor, or more pages than the bound is an error.
pub fn edit_history(
    runner: &Runner,
    reference: &IssueRef,
    limits: Limits,
) -> Result<Body, GhError> {
    let source = format!("gh api graphql (edit history of {reference})");
    let mut text = None;
    let mut editors = Vec::new();
    let mut after: Option<String> = None;
    let mut seen = BTreeSet::new();
    for _ in 0..limits.edit_history_pages {
        let mut argv = args(&[
            "api",
            "graphql",
            "-f",
            &format!("query={EDIT_HISTORY_QUERY}"),
            "-f",
            &format!("owner={}", reference.owner()),
            "-f",
            &format!("name={}", reference.repo()),
            "-F",
            &format!("number={}", reference.number()),
        ]);
        if let Some(cursor) = &after {
            argv.extend(args(&["-f", &format!("after={cursor}")]));
        }
        let value = json(&source, &runner.run_strict(&source, &argv)?)?;
        let issue = value
            .pointer("/data/repository/issue")
            .and_then(Value::as_object)
            .ok_or_else(|| GhError::invalid(&source, "GraphQL response has no issue"))?;
        if text.is_none() {
            text = Some(optional_text(&source, issue, "body")?.unwrap_or_default());
        }
        let edits = issue.get("userContentEdits").and_then(Value::as_object);
        let Some(nodes) = edits.and_then(|e| e.get("nodes")).and_then(Value::as_array) else {
            return Err(GhError::invalid(
                &source,
                "GraphQL response has no readable userContentEdits connection",
            ));
        };
        for node in nodes {
            editors.push(editor(&source, node)?);
        }
        let page = edits.and_then(|e| e.get("pageInfo"));
        let Some(&Value::Bool(next)) = page.and_then(|p| p.get("hasNextPage")) else {
            return Err(GhError::invalid(
                &source,
                "edit history has no boolean hasNextPage; refusing a partial editor list",
            ));
        };
        if !next {
            return Ok(Body {
                text: text.unwrap_or_default(),
                editors,
            });
        }
        let cursor = page
            .and_then(|p| p.get("endCursor"))
            .and_then(Value::as_str)
            .filter(|cursor| !cursor.is_empty())
            .ok_or_else(|| {
                GhError::invalid(
                    &source,
                    "edit history reports another page but no cursor; refusing a partial editor list",
                )
            })?;
        if !seen.insert(cursor.to_owned()) {
            return Err(GhError::invalid(
                &source,
                "edit history repeated a cursor; refusing a partial editor list",
            ));
        }
        after = Some(cursor.to_owned());
    }
    Err(GhError::invalid(
        &source,
        format!(
            "edit history ran past {} pages; refusing a partial editor list",
            limits.edit_history_pages
        ),
    ))
}

/// The editor of one edit, `None` for a deleted account.
fn editor(source: &str, node: &Value) -> Result<Option<Actor>, GhError> {
    let editor = match node {
        Value::Null => return Ok(None),
        Value::Object(node) => match node.get("editor") {
            None | Some(Value::Null) => return Ok(None),
            Some(editor) => object(source, editor, "an editor")?,
        },
        _ => return Err(GhError::invalid(source, "an edit is not a JSON object")),
    };
    let Some(login) = optional_text(source, editor, "login")? else {
        return Ok(None);
    };
    Ok(Some(Actor {
        login,
        actor_type: text(source, editor, "__typename")?,
    }))
}

/// Whether a login can be put in a request path: a GitHub login is ASCII
/// letters, digits, `-` and, for managed users, `_`.
fn is_login(login: &str) -> bool {
    !login.is_empty()
        && login
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'))
}

/// The permission of `login` on `repo`, `None` when GitHub answers HTTP 404
/// (not a collaborator), exactly as the Python compiler distinguishes it.
pub fn permission(runner: &Runner, repo: &Repo, login: &str) -> Result<Option<String>, GhError> {
    let path = format!(
        "repos/{}/{}/collaborators/{login}/permission",
        repo.owner(),
        repo.name()
    );
    let source = format!("gh api {path}");
    if !is_login(login) {
        return Err(GhError::invalid(
            &source,
            "the login is not a GitHub login; it is not put in a request path",
        ));
    }
    match runner.run(&source, &args(&["api", &path, "--jq", ".permission"])) {
        Ok(out) => {
            let permission = String::from_utf8(out)
                .map_err(|_| GhError::invalid(&source, "the permission is not UTF-8"))?;
            let permission = permission.trim();
            if permission.is_empty() {
                return Err(GhError::invalid(&source, "the permission is empty"));
            }
            Ok(Some(permission.to_owned()))
        }
        Err(Refusal::NotFound) => Ok(None),
        Err(Refusal::Failed(error)) => Err(error),
    }
}

/// The first CODEOWNERS file of `repo` (bundle rule OB11), `None` when
/// every path answers HTTP 404. Any other failure ends the search.
pub fn codeowners(runner: &Runner, repo: &Repo) -> Result<Option<CodeownersFile>, GhError> {
    for path in CODEOWNERS_PATHS {
        let api = format!("repos/{}/{}/contents/{path}", repo.owner(), repo.name());
        let source = format!("gh api {api}");
        let argv = args(&["api", &api, "-H", "Accept: application/vnd.github.raw+json"]);
        match runner.run(&source, &argv) {
            Ok(out) => {
                let text = String::from_utf8(out)
                    .map_err(|_| GhError::invalid(&source, "the file is not UTF-8"))?;
                return Ok(Some(CodeownersFile {
                    path: path.to_owned(),
                    text,
                }));
            }
            Err(Refusal::NotFound) => {}
            Err(Refusal::Failed(error)) => return Err(error),
        }
    }
    Ok(None)
}
