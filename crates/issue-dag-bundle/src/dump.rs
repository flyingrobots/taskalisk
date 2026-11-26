//! Writes a bundle, the inverse of [`crate::load`]
//! (flyingrobots/taskalisk#59): a live run's observations as an
//! `issue-dag-observations/1` bundle that a replay plans from offline.
//!
//! A slot that was not recorded is left out, never written empty (OB5), and
//! a body the run did not read is left out of its issue (OB14). The bundle
//! is compact JSON with its members in ascending order, so one run always
//! writes the same bytes.

use issue_dag_core::{
    Actor, Body, Bundle, CodeownersFile, Issue, IssueState, Observations, Observed, Parameters,
    PullRequest,
};
use serde_json::{Map, Value, json};

use crate::{BUNDLE_VERSION, FORMAT, PROFILE};

/// The bundle as compact JSON, members in ascending order.
#[must_use]
pub fn dump(bundle: &Bundle) -> String {
    json!({
        "bundle": BUNDLE_VERSION,
        "format": FORMAT,
        "profile": PROFILE,
        "parameters": parameters(&bundle.parameters),
        "observations": observations(&bundle.observations),
    })
    .to_string()
}

fn parameters(p: &Parameters) -> Value {
    json!({
        "home": p.home.to_string(),
        "roots": p.roots,
        "read_scope": {
            "owners": p.read_scope.owners,
            "repositories": p
                .read_scope
                .repositories
                .iter()
                .map(ToString::to_string)
                .collect::<Vec<_>>(),
        },
        "trust": {
            "policy": p.trust.policy,
            "logins": p.trust.logins,
            "codeowners": p.trust.codeowners,
        },
        "capacities": p.capacities,
    })
}

/// A slot (OB4).
fn slot<T>(observed: &Observed<T>, value: impl FnOnce(&T) -> Value) -> Value {
    match observed {
        Observed::Value(v) => json!({"value": value(v)}),
        Observed::Unavailable(why) => json!({"unavailable": why}),
    }
}

fn observations(o: &Observations) -> Value {
    let mut out = Map::new();
    if let Some(listing) = &o.home_open_issues {
        out.insert(
            "home_open_issues".into(),
            slot(listing, |refs| {
                json!(refs.iter().map(ToString::to_string).collect::<Vec<_>>())
            }),
        );
    }
    if let Some(pulls) = &o.home_open_pull_requests {
        out.insert(
            "home_open_pull_requests".into(),
            slot(pulls, |pulls| pulls.iter().map(pull_request).collect()),
        );
    }
    let issues: Map<String, Value> = o
        .issues
        .iter()
        .map(|(r, observed)| {
            let mut s = slot(observed, |i| issue(i, o.bodies.get(r)));
            if let (Observed::Unavailable(_), Some(cause)) = (observed, o.not_found.get(r)) {
                s["not_found"] = json!(cause.as_str());
            }
            (r.to_string(), s)
        })
        .collect();
    out.insert("issues".into(), Value::Object(issues));
    let permissions: Map<String, Value> = o
        .permissions
        .iter()
        .map(|(repo, logins)| {
            let table: Map<String, Value> = logins
                .iter()
                .map(|(login, level)| (login.clone(), slot(level, |l| json!(l))))
                .collect();
            (repo.to_string(), Value::Object(table))
        })
        .collect();
    out.insert("permissions".into(), Value::Object(permissions));
    if let Some(files) = &o.codeowners {
        let files: Map<String, Value> = files
            .iter()
            .map(|(repo, file)| (repo.to_string(), slot(file, |f| codeowners(f.as_ref()))))
            .collect();
        out.insert("codeowners".into(), Value::Object(files));
    }
    Value::Object(out)
}

fn actor(a: Option<&Actor>) -> Value {
    a.map_or(
        Value::Null,
        |a| json!({"login": a.login, "type": a.actor_type}),
    )
}

fn pull_request(p: &PullRequest) -> Value {
    json!({
        "number": p.number,
        "repository": p.repository.to_string(),
        "head_repository": p.head_repository.as_ref().map(ToString::to_string),
        "cross_repository": p.cross_repository,
        "author": actor(p.author.as_ref()),
        // OB7: a boolean, or an unavailable slot.
        "draft": match &p.draft {
            Observed::Value(flag) => json!(flag),
            Observed::Unavailable(why) => json!({"unavailable": why}),
        },
        "closes": p.closes.iter().map(ToString::to_string).collect::<Vec<_>>(),
    })
}

fn issue(i: &Issue, body: Option<&Observed<Body>>) -> Value {
    let mut out = json!({
        "address": i.address.to_string(),
        "pull_request": i.pull_request,
        "state": match i.state {
            IssueState::Open => "open",
            IssueState::Closed => "closed",
        },
        "state_reason": i.state_reason,
        "author": actor(i.author.as_ref()),
        "author_association": i.author_association,
    });
    if let Some(body) = body {
        out["body"] = slot(body, |b| {
            json!({
                "text": b.text,
                "editors": b.editors.iter().map(Option::as_ref).map(actor).collect::<Vec<_>>(),
            })
        });
    }
    out
}

fn codeowners(file: Option<&CodeownersFile>) -> Value {
    file.map_or(Value::Null, |f| json!({"path": f.path, "text": f.text}))
}
