//! The gh adapter against GitHub itself. Ignored by default because it needs
//! the network and an authenticated `gh`; run it with
//! `ISSUE_DAG_LIVE_REPO=owner/repo cargo test -p issue-dag-gh --test live -- --ignored`.
#![cfg(unix)]

use std::collections::BTreeSet;
use std::process::Command;

use issue_dag_core::{Forge, Observed, Repo};
use issue_dag_gh::GhForge;
use serde_json::Value;

fn live_repo() -> String {
    std::env::var("ISSUE_DAG_LIVE_REPO").expect("set ISSUE_DAG_LIVE_REPO to owner/repo")
}

/// The numbers `gh <kind> list` reports open, read independently of the adapter.
fn gh_list(kind: &str, repo: &str) -> BTreeSet<u64> {
    let out = Command::new("gh")
        .args([
            kind, "list", "--repo", repo, "--state", "open", "--limit", "1000",
        ])
        .args(["--json", "number"])
        .output()
        .expect("gh runs");
    assert!(out.status.success(), "gh {kind} list failed");
    let rows: Vec<Value> = serde_json::from_slice(&out.stdout).expect("JSON");
    rows.iter()
        .map(|row| row["number"].as_u64().expect("a number"))
        .collect()
}

#[test]
#[ignore = "needs the network and an authenticated gh"]
fn the_open_issues_are_the_ones_gh_lists() {
    let name = live_repo();
    let forge = GhForge::new(Repo::parse(&name).expect("owner/repo"));
    let Ok(Observed::Value(issues)) = forge.home_open_issues() else {
        panic!("open issues unavailable: {:?}", forge.failures());
    };
    let read: BTreeSet<u64> = issues.iter().map(|r| u64::from(r.number())).collect();
    assert_eq!(read.len(), issues.len(), "an issue listed twice");
    assert_eq!(read, gh_list("issue", &name));
}

#[test]
#[ignore = "needs the network and an authenticated gh"]
fn the_open_pull_requests_are_the_ones_gh_lists() {
    let name = live_repo();
    let forge = GhForge::new(Repo::parse(&name).expect("owner/repo"));
    let Ok(Observed::Value(prs)) = forge.home_open_pull_requests() else {
        panic!("open pull requests unavailable: {:?}", forge.failures());
    };
    let read: BTreeSet<u64> = prs.iter().map(|pr| pr.number).collect();
    assert_eq!(read, gh_list("pr", &name));
}

#[test]
#[ignore = "needs the network and an authenticated gh"]
fn every_open_issue_reads_with_its_body() {
    let name = live_repo();
    let forge = GhForge::new(Repo::parse(&name).expect("owner/repo"));
    let Ok(Observed::Value(issues)) = forge.home_open_issues() else {
        panic!("open issues unavailable: {:?}", forge.failures());
    };
    let first = issues.first().expect("the repository has an open issue");
    let Ok(Observed::Value(issue)) = forge.issue(first) else {
        panic!("{first} unavailable: {:?}", forge.failures());
    };
    assert_eq!(&issue.address, first);
    assert!(!issue.pull_request);
    let body = forge.body(first);
    assert!(
        matches!(&body, Ok(Observed::Value(body)) if !body.text.is_empty()),
        "{first}: body {body:?}"
    );
    assert!(forge.failures().is_empty(), "{:?}", forge.failures());
}
