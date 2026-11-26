//! The gh adapter against a fake `gh`, and the in-memory forge of the core
//! through the same assertions.
#![cfg(unix)]

mod fake;

use std::collections::BTreeMap;

use fake::Fake;
use issue_dag_core::{
    Actor, Body, CodeownersFile, Forge, Issue, IssueRef, IssueState, Observations, Observed,
    Outcome, Parameters, PullRequest, ReadScope, RecordedForge, Repo, TRUST_POLICY,
    TrustParameters, plan,
};
use issue_dag_gh::{GhError, GhForge, Limits};
use serde_json::{Value, json};

fn reference(text: &str) -> IssueRef {
    IssueRef::parse(text).expect("a reference")
}

fn repo(text: &str) -> Repo {
    Repo::parse(text).expect("a repository")
}

fn actor(login: &str, actor_type: &str) -> Actor {
    Actor {
        login: login.to_owned(),
        actor_type: actor_type.to_owned(),
    }
}

/// One GitHub, as the fake's state: every kind of read has an answer.
fn state() -> Value {
    json!({
        "home": "o/r",
        "edits_page_size": 2,
        "issues": {
            "o/r#1": {"id": 1, "title": "t", "state": "open", "body": "rest body",
                      "graphql_body": "B1", "author": "o", "association": "OWNER"},
            "o/r#2": {"id": 2, "title": "t", "state": "closed", "state_reason": "completed",
                      "body": "B2", "author": "Dev", "association": "CONTRIBUTOR",
                      "editors": ["Dev", null, {"login": "helper", "type": "Bot"}]},
            "o/r#3": {"id": 3, "title": "t", "state": "open", "body": "", "is_pr": true},
            "o/r#4": {"id": 4, "title": "t", "state": "open", "body": "", "author": null,
                      "association": "NONE", "editors": [null]},
            "o/s#9": {"id": 9, "title": "t", "state": "open", "body": "moved"}
        },
        "moved": {"o/r#5": "o/s#9"},
        "blocked_by": {},
        "prs": [
            {"number": 10, "isDraft": false, "isCrossRepository": false, "url": "u",
             "author": {"login": "Dev", "is_bot": false},
             "closingIssuesReferences": [{"number": 1, "repository": {"name": "R", "owner": {"login": "O"}}}]},
            {"number": 11, "isDraft": "maybe", "isCrossRepository": true, "url": "u",
             "author": {"login": "app/helper", "is_bot": true},
             "closingIssuesReferences": []},
            {"number": 12, "isDraft": true, "url": "u", "author": null,
             "closingIssuesReferences": [{"number": 2}]}
        ],
        "collaborators": {"o/r": {"dev": "write", "tri": "triage"}},
        "codeowners": {"o/r": {"CODEOWNERS": "* @o"}}
    })
}

/// The issues the state above resolves, and the body of each issue it
/// resolves, recorded by hand.
fn recorded_issues() -> (
    BTreeMap<IssueRef, Observed<Issue>>,
    BTreeMap<IssueRef, Observed<Body>>,
) {
    let issue = |address: &str, state, author: Option<Actor>, association: &str| Issue {
        address: reference(address),
        pull_request: false,
        state,
        state_reason: None,
        author,
        author_association: Some(association.to_owned()),
    };
    let mut issues = BTreeMap::new();
    let mut bodies = BTreeMap::new();
    let mut add = |key: &str, read: Issue, body: Observed<Body>| {
        issues.insert(reference(key), Observed::Value(read));
        bodies.insert(reference(key), body);
    };
    add(
        "o/r#1",
        issue("o/r#1", IssueState::Open, Some(actor("o", "User")), "OWNER"),
        Observed::Value(Body {
            text: "B1".to_owned(),
            editors: vec![Some(actor("o", "User"))],
        }),
    );
    add(
        "o/r#2",
        Issue {
            state_reason: Some("completed".to_owned()),
            ..issue(
                "o/r#2",
                IssueState::Closed,
                Some(actor("Dev", "User")),
                "CONTRIBUTOR",
            )
        },
        Observed::Value(Body {
            text: "B2".to_owned(),
            editors: vec![
                Some(actor("Dev", "User")),
                None,
                Some(actor("helper", "Bot")),
            ],
        }),
    );
    add(
        "o/r#3",
        Issue {
            pull_request: true,
            ..issue(
                "o/r#3",
                IssueState::Open,
                Some(actor("owner", "User")),
                "OWNER",
            )
        },
        Observed::Unavailable("o/r#3 is a pull request; its body is not read".to_owned()),
    );
    add(
        "o/r#4",
        issue("o/r#4", IssueState::Open, None, "NONE"),
        Observed::Value(Body {
            text: String::new(),
            editors: vec![None],
        }),
    );
    add(
        "o/r#5",
        issue(
            "o/s#9",
            IssueState::Open,
            Some(actor("owner", "User")),
            "OWNER",
        ),
        Observed::Unavailable("o/r#5 was transferred to o/s#9; its body is not read".to_owned()),
    );
    // An issue that cannot be read has no body to read or record.
    issues.insert(
        reference("o/r#404"),
        Observed::Unavailable("o/r#404 resolves to no issue gh can see (HTTP 404)".to_owned()),
    );
    (issues, bodies)
}

/// What the state above observes, recorded by hand.
fn recorded() -> Observations {
    let pull = |number, cross, author, draft, closes: &[&str]| PullRequest {
        number,
        repository: repo("o/r"),
        head_repository: None,
        cross_repository: cross,
        author,
        draft,
        closes: closes.iter().map(|r| reference(r)).collect(),
    };
    let mut permissions = BTreeMap::new();
    permissions.insert(
        repo("o/r"),
        BTreeMap::from([
            ("dev".to_owned(), Observed::Value(Some("write".to_owned()))),
            ("stranger".to_owned(), Observed::Value(None)),
        ]),
    );
    let (issues, bodies) = recorded_issues();
    Observations {
        home_open_issues: Some(Observed::Value(vec![
            reference("o/r#1"),
            reference("o/r#4"),
        ])),
        home_open_pull_requests: Some(Observed::Value(vec![
            pull(
                10,
                Some(false),
                Some(actor("Dev", "User")),
                Observed::Value(false),
                &["o/r#1"],
            ),
            pull(
                11,
                Some(true),
                Some(actor("app/helper", "Bot")),
                Observed::Unavailable("pull request 11 has no boolean isDraft".to_owned()),
                &[],
            ),
            pull(12, None, None, Observed::Value(true), &["o/r#2"]),
        ])),
        issues,
        bodies,
        permissions,
        codeowners: Some(BTreeMap::from([
            (
                repo("o/r"),
                Observed::Value(Some(CodeownersFile {
                    path: "CODEOWNERS".to_owned(),
                    text: "* @o\n".to_owned(),
                })),
            ),
            (repo("o/s"), Observed::Value(None)),
        ])),
    }
}

/// Every lookup the fixture holds, made through the port.
fn assert_fixture<F: Forge + ?Sized>(forge: &F) {
    let want = recorded();
    assert_eq!(
        forge.home_open_issues(),
        Ok(want.home_open_issues.clone().expect("recorded"))
    );
    assert_eq!(
        forge.home_open_pull_requests(),
        Ok(want.home_open_pull_requests.clone().expect("recorded"))
    );
    for (key, slot) in &want.issues {
        assert_eq!(forge.issue(key), Ok(slot.clone()), "{key}");
        // The body is its own read; an issue that cannot be read has none.
        let body = match slot {
            Observed::Value(_) => want.bodies[key].clone(),
            Observed::Unavailable(why) => Observed::Unavailable(why.clone()),
        };
        assert_eq!(forge.body(key), Ok(body), "the body of {key}");
    }
    for (on, table) in &want.permissions {
        for (login, slot) in table {
            assert_eq!(forge.permission(on, login), Ok(slot.clone()), "{login}");
        }
    }
    for (on, slot) in want.codeowners.as_ref().expect("recorded") {
        assert_eq!(forge.codeowners(on), Ok(slot.clone()), "{on}");
    }
}

#[test]
fn the_in_memory_forge_answers_the_fixture() {
    let observations = recorded();
    assert_fixture(&RecordedForge::new(&observations));
}

#[test]
fn the_gh_forge_answers_the_fixture_through_the_same_port() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r");
    assert_fixture(&forge);
    assert_eq!(forge.failures(), Vec::new());
    // What it read is a recording the in-memory forge replays.
    assert_eq!(forge.observations(), recorded());
}

#[test]
fn each_slot_is_one_lookup_whatever_the_number_of_reads() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r");
    let first = forge.issue(&reference("o/r#2"));
    let calls = fake.calls().len();
    assert_eq!(forge.issue(&reference("o/r#2")), first);
    assert_eq!(
        forge.permission(&repo("o/r"), "dev"),
        forge.permission(&repo("o/r"), "dev")
    );
    assert_eq!(fake.calls().len(), calls + 1);
}

#[test]
fn the_gh_invocations_are_argument_vectors_with_the_python_limits() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r");
    assert_fixture(&forge);
    let calls = fake.calls();
    let has = |want: &[&str]| calls.iter().any(|c| c == want);
    assert!(has(&[
        "api",
        "--paginate",
        "repos/o/r/issues?state=open&per_page=100"
    ]));
    assert!(has(&[
        "pr",
        "list",
        "--repo",
        "o/r",
        "--state",
        "open",
        "--limit",
        "500",
        "--json",
        "number,isDraft,closingIssuesReferences,author,isCrossRepository",
    ]));
    assert!(has(&["api", "repos/o/r/issues/2"]));
    assert!(has(&[
        "api",
        "repos/o/r/collaborators/dev/permission",
        "--jq",
        ".permission"
    ]));
    for path in [".github/CODEOWNERS", "CODEOWNERS"] {
        assert!(has(&[
            "api",
            &format!("repos/o/r/contents/{path}"),
            "-H",
            "Accept: application/vnd.github.raw+json",
        ]));
    }
    // The first CODEOWNERS found ends the search.
    assert!(!has(&[
        "api",
        "repos/o/r/contents/docs/CODEOWNERS",
        "-H",
        "Accept: application/vnd.github.raw+json",
    ]));
    // Edit history: two editors a page, so #2's three editors take two pages.
    let history: Vec<_> = calls
        .iter()
        .filter(|c| c[..2] == ["api", "graphql"] && c.contains(&"number=2".to_owned()))
        .collect();
    assert_eq!(history.len(), 2);
    assert!(history[0][2..].starts_with(&[
        "-f".to_owned(),
        format!("query={}", issue_dag_gh::EDIT_HISTORY_QUERY),
        "-f".to_owned(),
        "owner=o".to_owned(),
        "-f".to_owned(),
        "name=r".to_owned(),
        "-F".to_owned(),
        "number=2".to_owned(),
    ]));
    assert!(history[1].ends_with(&["-f".to_owned(), "after=2".to_owned()]));
    // A pull request and a transferred issue cost no edit-history query.
    assert!(!calls.iter().any(|c| c.contains(&"number=3".to_owned())));
    assert!(!calls.iter().any(|c| c.contains(&"number=5".to_owned())));
    assert!(!calls.iter().any(|c| c.contains(&"number=9".to_owned())));
}

#[test]
fn the_default_limits_are_the_python_compilers() {
    assert_eq!(
        Limits::default(),
        Limits {
            issues: 1000,
            pull_requests: 500,
            edit_history_pages: 1000,
        }
    );
}

/// The one failure a forge recorded, and the slot it answered with.
fn failed<T: std::fmt::Debug + PartialEq>(forge: &GhForge, slot: &Observed<T>) -> GhError {
    assert!(matches!(slot, Observed::Unavailable(_)), "{slot:?}");
    let failures = forge.failures();
    assert_eq!(failures.len(), 1, "{failures:?}");
    assert_eq!(
        *slot,
        Observed::Unavailable(failures[0].to_string()),
        "the slot says why"
    );
    failures[0].clone()
}

fn with(changes: &Value) -> Value {
    let mut base = state();
    for (key, value) in changes.as_object().expect("an object") {
        base[key] = value.clone();
    }
    base
}

/// #122: the tests run on parallel threads, and Linux refuses to run a file
/// that any process holds open for writing (`ETXTBSY`). A child forked by
/// one test while another writes its `gh` keeps that descriptor until its own
/// exec, so a written `gh` sometimes "could not be run". A symlink to the
/// checked-in fake is never open for writing.
#[test]
fn the_fake_gh_is_a_symlink_to_the_checked_in_fake_never_a_written_file() {
    let fake = Fake::new(&state());
    let gh = fake.gh();
    let kind = std::fs::symlink_metadata(&gh)
        .expect("the fake's gh")
        .file_type();
    assert!(kind.is_symlink(), "{} is a written file", gh.display());
    let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fake_gh.py");
    assert_eq!(
        std::fs::canonicalize(&gh).expect("the link resolves"),
        script.canonicalize().expect("tests/fake_gh.py")
    );
}

#[test]
fn a_listing_that_fills_its_limit_is_unavailable_never_a_short_list() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r").limits(Limits {
        issues: 2,
        ..Limits::default()
    });
    let slot = forge.home_open_issues().expect("never missing");
    assert_eq!(failed(&forge, &slot).code(), "gh.list_limit_reached");

    let forge = fake.forge("o/r").limits(Limits {
        pull_requests: 3,
        ..Limits::default()
    });
    let slot = forge.home_open_pull_requests().expect("never missing");
    let error = failed(&forge, &slot);
    assert_eq!(error.code(), "gh.list_limit_reached");
    assert!(error.to_string().contains("--limit 3"), "{error}");
    assert!(fake.calls().iter().any(|c| c.contains(&"3".to_owned())));
}

#[test]
fn a_listing_below_its_limit_is_complete() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r").limits(Limits {
        issues: 3,
        pull_requests: 4,
        ..Limits::default()
    });
    assert!(matches!(forge.home_open_issues(), Ok(Observed::Value(v)) if v.len() == 2));
    assert!(matches!(forge.home_open_pull_requests(), Ok(Observed::Value(v)) if v.len() == 3));
    assert_eq!(forge.failures(), Vec::new());
}

#[test]
fn a_failed_listing_is_unavailable_never_empty() {
    let fake = Fake::new(&with(
        &json!({"issues_list_fail_message": "gh: Bad Gateway (HTTP 502)"}),
    ));
    let forge = fake.forge("o/r");
    let slot = forge.home_open_issues().expect("never missing");
    let error = failed(&forge, &slot);
    assert_eq!(error.code(), "gh.command_failed");
    assert!(error.to_string().contains("HTTP 502"), "{error}");
}

#[test]
fn a_listing_of_the_wrong_shape_is_unavailable() {
    for change in [
        json!({"issues_list_returns_object": true}),
        json!({"issues_list_drop_number": true}),
    ] {
        let fake = Fake::new(&with(&change));
        let forge = fake.forge("o/r");
        let slot = forge.home_open_issues().expect("never missing");
        assert_eq!(
            failed(&forge, &slot).code(),
            "gh.response_invalid",
            "{change}"
        );
    }
}

#[test]
fn a_pull_request_list_of_the_wrong_shape_is_unavailable() {
    for prs in [
        json!([{"number": "ten", "isDraft": false, "closingIssuesReferences": []}]),
        json!([{"number": 10, "isDraft": false, "closingIssuesReferences": [{"repository": {}}]}]),
        json!([{"number": 10, "isDraft": false, "isCrossRepository": "no", "closingIssuesReferences": []}]),
    ] {
        let fake = Fake::new(&with(&json!({ "prs": prs })));
        let forge = fake.forge("o/r");
        let slot = forge.home_open_pull_requests().expect("never missing");
        assert_eq!(failed(&forge, &slot).code(), "gh.response_invalid", "{prs}");
    }
}

#[test]
fn an_issue_of_the_wrong_shape_is_unavailable() {
    let fake = Fake::new(&with(&json!({"issue_get_returns_list": true})));
    let forge = fake.forge("o/r");
    let slot = forge.issue(&reference("o/r#1")).expect("never missing");
    assert_eq!(failed(&forge, &slot).code(), "gh.response_invalid");
}

#[test]
fn an_issue_that_does_not_exist_is_unavailable_and_no_failure() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r");
    assert!(matches!(
        forge.issue(&reference("o/r#404")),
        Ok(Observed::Unavailable(_))
    ));
    assert_eq!(forge.failures(), Vec::new());
}

#[test]
fn a_failed_edit_history_leaves_the_body_unavailable() {
    for (change, code) in [
        (json!({"fail_graphql": true}), "gh.command_failed"),
        (json!({"graphql_null_edits": true}), "gh.response_invalid"),
        (json!({"graphql_no_cursor": true}), "gh.response_invalid"),
        (
            json!({"graphql_repeat_cursor": true}),
            "gh.response_invalid",
        ),
    ] {
        let fake = Fake::new(&with(&change));
        let forge = fake.forge("o/r");
        assert!(
            matches!(forge.issue(&reference("o/r#2")), Ok(Observed::Value(_))),
            "the issue itself was read ({change})"
        );
        let body = forge.body(&reference("o/r#2")).expect("never missing");
        assert_eq!(failed(&forge, &body).code(), code, "{change}");
    }
}

#[test]
fn an_edit_history_past_its_page_bound_is_refused() {
    let fake = Fake::new(&with(&json!({"edits_page_size": 1})));
    let forge = fake.forge("o/r").limits(Limits {
        edit_history_pages: 2,
        ..Limits::default()
    });
    assert!(
        matches!(forge.issue(&reference("o/r#2")), Ok(Observed::Value(_))),
        "the issue itself was read"
    );
    let body = forge.body(&reference("o/r#2")).expect("never missing");
    let error = failed(&forge, &body);
    assert_eq!(error.code(), "gh.response_invalid");
    assert!(error.to_string().contains("2 pages"), "{error}");
}

#[test]
fn a_permission_lookup_that_fails_other_than_404_is_unavailable_not_none() {
    let fake = Fake::new(&with(&json!({"collaborators_forbidden": true})));
    let forge = fake.forge("o/r");
    let slot = forge
        .permission(&repo("o/r"), "stranger")
        .expect("never missing");
    let error = failed(&forge, &slot);
    assert_eq!(error.code(), "gh.command_failed");
    assert!(error.to_string().contains("HTTP 403"), "{error}");
}

#[test]
fn a_login_that_is_not_a_github_login_is_never_put_in_a_path() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r");
    let slot = forge
        .permission(&repo("o/r"), "../../x")
        .expect("never missing");
    assert_eq!(failed(&forge, &slot).code(), "gh.response_invalid");
    assert_eq!(fake.calls(), Vec::<Vec<String>>::new());
}

#[test]
fn a_codeowners_fetch_that_fails_other_than_404_is_unavailable_not_none() {
    let fake = Fake::new(&with(&json!({"contents_fail": true})));
    let forge = fake.forge("o/r");
    let slot = forge.codeowners(&repo("o/r")).expect("never missing");
    let error = failed(&forge, &slot);
    assert_eq!(error.code(), "gh.command_failed");
    assert!(error.to_string().contains("HTTP 500"), "{error}");
}

#[test]
fn a_gh_that_cannot_be_run_is_a_failure() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r").program("gh-that-does-not-exist");
    let slot = forge.home_open_pull_requests().expect("never missing");
    assert_eq!(failed(&forge, &slot).code(), "gh.command_failed");
}

#[test]
fn a_token_in_gh_output_never_reaches_a_reason() {
    let fake = Fake::new(&with(
        &json!({"issues_list_fail_message": "token {GH_TOKEN} under {HOME} at https://u:pw@example.com/x"}),
    ));
    let forge = fake.forge("o/r").env("GH_TOKEN", "sekrit-token-value");
    let slot = forge.home_open_issues().expect("never missing");
    let reason = failed(&forge, &slot).to_string();
    assert!(!reason.contains("sekrit-token-value"), "{reason}");
    assert!(!reason.contains(":pw@"), "{reason}");
    let home = std::env::var("HOME").expect("HOME");
    assert!(!reason.contains(&home), "{reason}");
}

#[test]
fn a_failure_ends_the_run_incomplete_which_exits_2() {
    let fake = Fake::new(&with(
        &json!({"issues_list_fail_message": "gh: boom (HTTP 500)"}),
    ));
    let forge = fake.forge("o/r");
    let parameters = Parameters {
        home: repo("o/r"),
        roots: Vec::new(),
        read_scope: ReadScope {
            owners: ["o".to_owned()].into(),
            repositories: [repo("o/r")].into(),
        },
        trust: TrustParameters {
            policy: TRUST_POLICY.to_owned(),
            logins: Vec::new(),
            codeowners: false,
        },
        capacities: BTreeMap::new(),
    };
    let outcome = plan(&parameters, &forge).expect("the gh forge never answers missing");
    assert!(matches!(outcome, Outcome::Incomplete { .. }), "{outcome:?}");
    assert_eq!(forge.failures()[0].code(), "gh.command_failed");
    assert_eq!(GhError::EXIT_STATUS, 2);
}

/// The run parameters of the fixture's home, with these roots.
fn parameters(roots: &[&str]) -> Parameters {
    Parameters {
        home: repo("o/r"),
        roots: roots.iter().map(|r| (*r).to_owned()).collect(),
        read_scope: ReadScope {
            owners: ["o".to_owned()].into(),
            repositories: [repo("o/r")].into(),
        },
        trust: TrustParameters {
            policy: TRUST_POLICY.to_owned(),
            logins: Vec::new(),
            codeowners: false,
        },
        capacities: BTreeMap::new(),
    }
}

/// The edit-history queries the fake was asked, as the issue number each
/// one names.
fn edit_history_calls(fake: &Fake) -> Vec<String> {
    fake.calls()
        .iter()
        .filter(|c| c[..2] == ["api", "graphql"])
        .filter_map(|c| c.iter().find(|a| a.starts_with("number=")).cloned())
        .collect()
}

#[test]
fn c15_an_issue_read_costs_no_edit_history_query() {
    let fake = Fake::new(&state());
    let forge = fake.forge("o/r");
    assert!(matches!(
        forge.issue(&reference("o/r#2")),
        Ok(Observed::Value(_))
    ));
    assert!(forge.observations().bodies.is_empty());
    assert_eq!(edit_history_calls(&fake), Vec::<String>::new());
    // The body is read when asked for, once, every page of it.
    let body = forge.body(&reference("o/r#2"));
    assert_eq!(forge.body(&reference("o/r#2")), body);
    assert_eq!(edit_history_calls(&fake), ["number=2", "number=2"]);
}

#[test]
fn c15_a_run_over_a_strangers_issue_makes_no_edit_history_query() {
    let stranger = with(&json!({"issues": {
        "o/r#7": {"id": 7, "title": "t", "state": "open", "author": "stranger",
                  "association": "NONE",
                  "body": "```yaml\n.dag: issue-dag/2\n.id: o/r#7\n.kind: task\n.type: feature\n```\n"}
    }, "prs": []}));
    let fake = Fake::new(&stranger);
    let forge = fake.forge("o/r");
    let outcome = plan(&parameters(&["o/r#7"]), &forge).expect("never missing");
    let Outcome::Planned { graph, .. } = outcome else {
        panic!("expected a plan, got {outcome:?}");
    };
    assert!(graph.unmodeled.is_empty() && !graph.nodes.contains_key(&reference("o/r#7")));
    assert_eq!(edit_history_calls(&fake), Vec::<String>::new());
    assert_eq!(forge.failures(), Vec::new());
    // The recording leaves the body out: it was never read (bundle OB14).
    let recorded = forge.observations();
    assert!(matches!(
        recorded.issues.get(&reference("o/r#7")),
        Some(Observed::Value(_))
    ));
    assert_eq!(recorded.bodies.get(&reference("o/r#7")), None);
}

#[test]
fn c15_a_run_over_a_trusted_issue_reads_its_edit_history() {
    let fake = Fake::new(&with(&json!({"prs": []})));
    let forge = fake.forge("o/r");
    let outcome = plan(&parameters(&["o/r#1"]), &forge).expect("never missing");
    assert!(matches!(outcome, Outcome::Planned { .. }), "{outcome:?}");
    assert_eq!(edit_history_calls(&fake), ["number=1"]);
    let recorded = forge.observations();
    assert_eq!(
        recorded.bodies.get(&reference("o/r#1")),
        Some(&Observed::Value(Body {
            text: "B1".to_owned(),
            editors: vec![Some(actor("o", "User"))],
        }))
    );
    // What the run read replays to the same outcome.
    assert_eq!(
        plan(&parameters(&["o/r#1"]), &RecordedForge::new(&recorded)),
        Ok(outcome)
    );
}

#[test]
fn ob6_a_listing_reads_every_page_gh_paginates() {
    let fake = Fake::new(&with(
        &json!({"issues_list_pages": [["o/r#1", "o/r#3"], ["o/r#4"]]}),
    ));
    let forge = fake.forge("o/r");
    assert_eq!(
        forge.home_open_issues(),
        Ok(Observed::Value(vec![
            reference("o/r#1"),
            reference("o/r#4")
        ]))
    );
    assert_eq!(forge.failures(), Vec::new());
}

#[test]
fn ob6_an_issue_listed_on_two_pages_makes_the_listing_unavailable() {
    // GitHub's pages shift under a concurrent change: an issue seen twice
    // means another may have been missed.
    let fake = Fake::new(&with(
        &json!({"issues_list_pages": [["o/r#1", "o/r#4"], ["o/r#4"]]}),
    ));
    let forge = fake.forge("o/r");
    let slot = forge.home_open_issues().expect("never missing");
    let error = failed(&forge, &slot);
    assert_eq!(error.code(), "gh.response_invalid");
    assert!(error.to_string().contains("o/r#4"), "{error}");
}

#[test]
fn a_has_next_page_that_is_missing_or_not_a_boolean_is_refused() {
    for page_info in [
        json!({"endCursor": "2"}),
        json!({"hasNextPage": "false", "endCursor": "2"}),
        json!({"hasNextPage": null, "endCursor": "2"}),
    ] {
        let fake = Fake::new(&with(&json!({ "graphql_page_info": page_info })));
        let forge = fake.forge("o/r");
        let body = forge.body(&reference("o/r#1")).expect("never missing");
        let error = failed(&forge, &body);
        assert_eq!(error.code(), "gh.response_invalid", "{page_info}");
        assert!(error.to_string().contains("hasNextPage"), "{error}");
    }
}

#[test]
fn gh_runs_without_a_terminal_colour_debug_or_prompts() {
    let fake = Fake::new(&with(&json!({"record_env": [
        "GH_FORCE_TTY", "CLICOLOR_FORCE", "GH_DEBUG", "DEBUG",
        "GH_PROMPT_DISABLED", "NO_COLOR", "GH_NO_UPDATE_NOTIFIER", "GH_PAGER", "GH_HOST"
    ]})));
    // What the caller gives cannot turn the hardening off; the rest passes.
    let forge = fake
        .forge("o/r")
        .env("GH_FORCE_TTY", "1")
        .env("CLICOLOR_FORCE", "1")
        .env("GH_DEBUG", "api")
        .env("DEBUG", "1")
        .env("GH_PROMPT_DISABLED", "")
        .env("NO_COLOR", "")
        .env("GH_PAGER", "less")
        .env("GH_HOST", "example.com");
    let _ = forge.home_open_pull_requests();
    assert_eq!(
        fake.environments(),
        [json!({
            "GH_FORCE_TTY": null, "CLICOLOR_FORCE": null, "GH_DEBUG": null, "DEBUG": null,
            "GH_PROMPT_DISABLED": "1", "NO_COLOR": "1", "GH_NO_UPDATE_NOTIFIER": "1",
            "GH_PAGER": "cat", "GH_HOST": "example.com"
        })]
    );
}

#[test]
fn server_text_never_reaches_a_reason() {
    let secret = "server-said-sekrit";
    let prs = json!([{"number": 10, "isDraft": false, "closingIssuesReferences": [
        {"number": 1, "repository": {"name": format!("{secret} x"), "owner": {"login": "o"}}}
    ]}]);
    let fake = Fake::new(&with(&json!({ "prs": prs })));
    let forge = fake.forge("o/r");
    let slot = forge.home_open_pull_requests().expect("never missing");
    let reason = failed(&forge, &slot).to_string();
    assert!(!reason.contains(secret), "{reason}");

    let mut odd = state();
    odd["issues"]["o/r#1"]["state"] = json!(secret);
    let fake = Fake::new(&odd);
    let forge = fake.forge("o/r");
    let slot = forge.issue(&reference("o/r#1")).expect("never missing");
    let error = failed(&forge, &slot);
    assert_eq!(error.code(), "gh.response_invalid");
    assert!(!error.to_string().contains(secret), "{error}");
}

#[test]
fn a_draft_flag_that_is_not_a_boolean_is_unavailable_not_a_failure() {
    for flag in [json!("maybe"), json!(null), json!(1)] {
        let prs = json!([{"number": 10, "isDraft": flag, "isCrossRepository": false,
                          "author": null, "closingIssuesReferences": []}]);
        let fake = Fake::new(&with(&json!({ "prs": prs })));
        let forge = fake.forge("o/r");
        let Ok(Observed::Value(pulls)) = forge.home_open_pull_requests() else {
            panic!("the list itself was read ({flag})");
        };
        assert_eq!(
            pulls[0].draft,
            Observed::Unavailable("pull request 10 has no boolean isDraft".to_owned()),
            "{flag}"
        );
        assert_eq!(forge.failures(), Vec::new(), "{flag}");
    }
}

#[test]
fn an_empty_permission_is_unavailable_never_none() {
    let fake = Fake::new(&with(&json!({"collaborators": {"o/r": {"dev": ""}}})));
    let forge = fake.forge("o/r");
    let slot = forge
        .permission(&repo("o/r"), "dev")
        .expect("never missing");
    assert_eq!(failed(&forge, &slot).code(), "gh.response_invalid");
}

#[test]
fn ob6_a_listing_that_prints_nothing_is_unavailable_never_empty() {
    let fake = Fake::new(&with(&json!({"issues_list_silent": true})));
    let forge = fake.forge("o/r");
    let slot = forge.home_open_issues().expect("never missing");
    let error = failed(&forge, &slot);
    assert_eq!(error.code(), "gh.response_invalid");
    assert!(error.to_string().contains("no page"), "{error}");
}

#[test]
fn c15_a_run_over_strangers_listed_issues_makes_no_query_beyond_the_lists() {
    let task = |n: u32| {
        format!("```yaml\n.dag: issue-dag/2\n.id: o/r#{n}\n.kind: task\n.type: feature\n```\n")
    };
    let strangers: serde_json::Map<String, Value> = (1..=3)
        .map(|n| {
            (
                format!("o/r#{n}"),
                json!({"id": n, "title": "t", "state": "open", "author": "stranger",
                       "association": "NONE", "body": task(n)}),
            )
        })
        .collect();
    let fake = Fake::new(&with(&json!({"issues": strangers, "prs": []})));
    let forge = fake.forge("o/r");
    let outcome = plan(&parameters(&[]), &forge).expect("never missing");
    let Outcome::Planned { graph, .. } = &outcome else {
        panic!("expected a plan, got {outcome:?}");
    };
    assert_eq!(graph.untrusted.len(), 3, "{graph:?}");
    // The listing fills each issue: no issue GET, no edit history.
    assert_eq!(
        fake.calls(),
        [
            vec![
                "api",
                "--paginate",
                "repos/o/r/issues?state=open&per_page=100"
            ],
            vec![
                "pr",
                "list",
                "--repo",
                "o/r",
                "--state",
                "open",
                "--limit",
                "500",
                "--json",
                "number,isDraft,closingIssuesReferences,author,isCrossRepository",
            ],
        ]
    );
    assert_eq!(forge.failures(), Vec::new());
    // The listed issues are recorded as read, so the run replays.
    let recorded = forge.observations();
    assert_eq!(recorded.issues.len(), 3);
    assert_eq!(
        plan(&parameters(&[]), &RecordedForge::new(&recorded)),
        Ok(outcome)
    );
}
