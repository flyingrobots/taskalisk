//! The bundle writer, [`dump`]: the inverse of [`load`]
//! (flyingrobots/taskalisk#59). A live run records its observations through
//! it, so what it writes must load back to the same bundle, and must be the
//! bundle the corpus holds when given the corpus's bundles.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use issue_dag_bundle::{dump, load};
use issue_dag_core::{
    Actor, Body, Bundle, Issue, IssueRef, IssueState, NotFound, Observations, Observed, Parameters,
    PullRequest, ReadScope, Repo, TRUST_POLICY, TrustParameters,
};
use serde_json::Value;

fn corpus_bundles() -> Vec<PathBuf> {
    fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
        for entry in fs::read_dir(dir).expect("a corpus directory") {
            let path = entry.expect("an entry").path();
            if path.is_dir() {
                walk(&path, out);
            } else if path.file_name().is_some_and(|n| n == "bundle.json") {
                out.push(path);
            }
        }
    }
    let mut out = Vec::new();
    walk(
        &Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/issue-dag/corpus/cases"),
        &mut out,
    );
    out.sort();
    out
}

#[test]
fn every_corpus_bundle_dumps_to_the_bundle_it_was_read_from() {
    let bundles = corpus_bundles();
    assert!(bundles.len() > 20, "the corpus has its bundles");
    for path in bundles {
        let text = fs::read_to_string(&path).expect("a bundle");
        let Ok(bundle) = load(&text) else {
            // A bundle the reader rejects has no domain value to write.
            continue;
        };
        let written = dump(&bundle);
        assert_eq!(
            load(&written).as_ref(),
            Ok(&bundle),
            "{}: the dump does not load back",
            path.display()
        );
        let original: Value = serde_json::from_str(&text).expect("JSON");
        let dumped: Value = serde_json::from_str(&written).expect("JSON");
        assert_eq!(dumped, original, "{}: the dump is not the bundle", path.display());
    }
}

fn reference(text: &str) -> IssueRef {
    IssueRef::parse(text).expect("a reference")
}

fn repo(text: &str) -> Repo {
    Repo::parse(text).expect("a repository")
}

fn actor(login: &str) -> Actor {
    Actor {
        login: login.to_owned(),
        actor_type: "User".to_owned(),
    }
}

/// A bundle with every kind of slot: a value, an unavailable one, a cause,
/// a body left out, a draft flag that was not a boolean, a deleted author.
fn every_slot() -> Bundle {
    let home = repo("o/r");
    let mut observations = Observations {
        home_open_issues: Some(Observed::Value(vec![reference("o/r#1"), reference("o/r#2")])),
        home_open_pull_requests: Some(Observed::Value(vec![PullRequest {
            number: 7,
            repository: home.clone(),
            head_repository: None,
            cross_repository: Some(false),
            author: None,
            draft: Observed::Unavailable("the draft flag was \"yes\"".to_owned()),
            closes: vec![reference("o/r#1")],
        }])),
        codeowners: Some(BTreeMap::from([(
            home.clone(),
            Observed::Unavailable("HTTP 500".to_owned()),
        )])),
        ..Observations::default()
    };
    let issue = |author: Option<Actor>| Issue {
        address: reference("o/r#1"),
        pull_request: false,
        state: IssueState::Open,
        state_reason: None,
        author,
        author_association: Some("OWNER".to_owned()),
    };
    observations
        .issues
        .insert(reference("o/r#1"), Observed::Value(issue(Some(actor("o")))));
    observations.bodies.insert(
        reference("o/r#1"),
        Observed::Value(Body {
            text: "```yaml\n.dag: issue-dag/2\n```\n".to_owned(),
            editors: vec![Some(actor("o")), None],
        }),
    );
    let mut two = issue(None);
    two.address = reference("o/r#2");
    two.state = IssueState::Closed;
    two.state_reason = Some("completed".to_owned());
    observations
        .issues
        .insert(reference("o/r#2"), Observed::Value(two));
    observations.issues.insert(
        reference("o/r#3"),
        Observed::Unavailable("HTTP 404".to_owned()),
    );
    observations
        .not_found
        .insert(reference("o/r#3"), NotFound::Number);
    observations.permissions.insert(
        home.clone(),
        BTreeMap::from([
            ("o".to_owned(), Observed::Value(Some("admin".to_owned()))),
            ("carol".to_owned(), Observed::Value(None)),
            ("dave".to_owned(), Observed::Unavailable("HTTP 403".to_owned())),
        ]),
    );
    Bundle {
        parameters: Parameters {
            home,
            roots: Vec::new(),
            read_scope: ReadScope {
                owners: ["o".to_owned()].into(),
                repositories: [repo("p/q")].into(),
            },
            trust: TrustParameters {
                policy: TRUST_POLICY.to_owned(),
                logins: vec!["dev".to_owned()],
                codeowners: true,
            },
            capacities: BTreeMap::from([("gpu".to_owned(), 2)]),
        },
        observations,
    }
}

#[test]
fn every_kind_of_slot_survives_a_dump() {
    let bundle = every_slot();
    let written = dump(&bundle);
    assert_eq!(load(&written), Ok(bundle));
    let value: Value = serde_json::from_str(&written).expect("JSON");
    let issues = &value["observations"]["issues"];
    assert_eq!(issues["o/r#3"]["not_found"], "number");
    // A body the run did not read is left out, never written empty (OB14).
    assert!(issues["o/r#2"]["value"].get("body").is_none());
    assert_eq!(
        value["observations"]["home_open_pull_requests"]["value"][0]["draft"]["unavailable"],
        "the draft flag was \"yes\""
    );
}

#[test]
fn a_dump_is_compact_with_its_members_in_order() {
    let written = dump(&every_slot());
    let value: Value = serde_json::from_str(&written).expect("JSON");
    assert_eq!(written, value.to_string(), "compact, members sorted");
    assert_eq!(dump(&every_slot()), written, "the same bytes every time");
}

#[test]
fn observations_never_recorded_are_left_out_not_written_empty() {
    let mut bundle = every_slot();
    bundle.observations = Observations::default();
    bundle.parameters.trust.codeowners = false;
    let value: Value = serde_json::from_str(&dump(&bundle)).expect("JSON");
    // OB5: a slot not recorded is absent, so a replay that needs it fails
    // as missing rather than reading it as empty.
    let observations = value["observations"].as_object().expect("an object");
    assert!(!observations.contains_key("home_open_issues"));
    assert!(!observations.contains_key("home_open_pull_requests"));
    assert!(!observations.contains_key("codeowners"));
}
