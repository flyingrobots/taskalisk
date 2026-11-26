//! Runs every graph-level case of the vendored conformance corpus
//! (`tests/fixtures/issue-dag/corpus/cases/graph/`): each `bundle.json` is
//! read by this crate and planned by `issue-dag-core`, and the result is
//! projected into the corpus's expected form (corpus rule CC6).
//!
//! - A normative case passes when every member its expected result holds
//!   equals the crate's (CC8). An invalid run's graph is not asserted (F3).
//! - A `--python` twin records what the Python computes where it disagrees
//!   with the specification. The crate must match the normative case
//!   instead, on the twin's own input.
//! - A characterisation case without a normative twin is one where the
//!   Python and the specification agree; the crate must equal it exactly.
//!
//! A bundle that lacks a slot the run reads is `unusable`, with the slot
//! reported as `missing`; an incomplete run reports its `unavailable` reason
//! (OB16), which only a normative case states (CC6).
//!
//! `findings` compare as a set (CC6), and in a normative planned case every
//! member of the expected batch must be dispatchable (Q2). Every other
//! member compares exactly: `ready` in rank order (K6), `scores` (K5),
//! `waves` (K7), `critical_path` (K8), `batch` in order of selection,
//! `skipped` with reasons in the order considered, and `unknown_capacity`
//! in ascending order (B3, B5).

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use issue_dag_bundle::load;
use issue_dag_core::{Edge, Graph, IssueRef, Outcome, RecordedForge, Skip, plan, rank, select};
use serde_json::{Map, Value, json};

/// The members that describe the graph (CC6), its ranking and its batch,
/// not asserted for a normative invalid case (CC8, F3).
const GRAPH: [&str; 15] = [
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

fn corpus_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/issue-dag/corpus/cases/graph")
}

fn read_json(path: &Path) -> Value {
    let text = fs::read_to_string(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// A list in the corpus's order: objects by their `id`, or by `from`, `to`
/// and `status`; anything else by its JSON text.
fn sorted(mut items: Vec<Value>) -> Value {
    items.sort_by_key(|v| {
        ["id", "from", "to", "status", "subject", "rule", "concerns"]
            .iter()
            .map(|k| v.get(k).map_or_else(String::new, ToString::to_string))
            .chain([v.to_string()])
            .collect::<Vec<_>>()
    });
    Value::Array(items)
}

fn pairs(edges: &BTreeSet<Edge>) -> Value {
    sorted(
        edges
            .iter()
            .map(|e| json!({"from": e.from.to_string(), "to": e.to.to_string()}))
            .collect(),
    )
}

fn graph_json(graph: &Graph, out: &mut Map<String, Value>) {
    let nodes = graph
        .nodes
        .iter()
        .map(|(id, n)| {
            let mut node = json!({
                "id": id.to_string(),
                "complete": n.complete,
                "opaque": n.opaque,
                "untrusted": n.untrusted,
            });
            if let Some(status) = n.status {
                node["status"] = json!(status.as_str());
            }
            node
        })
        .collect();
    let containers = graph
        .containers
        .iter()
        .map(|(id, children)| {
            json!({
                "id": id.to_string(),
                "children": children.iter().map(ToString::to_string).collect::<Vec<_>>(),
            })
        })
        .collect();
    let refs = |set: &BTreeSet<issue_dag_core::IssueRef>| {
        sorted(set.iter().map(|r| json!(r.to_string())).collect())
    };
    let edges = graph
        .edges
        .iter()
        .map(|e| (e, "open"))
        .chain(graph.satisfied.iter().map(|e| (e, "satisfied")))
        .map(|(e, status)| {
            json!({"from": e.from.to_string(), "to": e.to.to_string(), "status": status})
        })
        .collect();
    out.insert("nodes".into(), sorted(nodes));
    out.insert("containers".into(), sorted(containers));
    out.insert("unmodeled".into(), refs(&graph.unmodeled));
    out.insert("untrusted".into(), refs(&graph.untrusted));
    out.insert(
        "untrusted_pull_requests".into(),
        json!(graph.untrusted_pull_requests),
    );
    out.insert("edges".into(), sorted(edges));
    out.insert("redundant".into(), pairs(&graph.redundant));
    out.insert("not_planned".into(), pairs(&graph.not_planned));
}

/// The ranking (K5 to K8) and the batch (B3, B5) of a graph.
fn ranking_json(graph: &Graph, capacities: &BTreeMap<String, u64>, out: &mut Map<String, Value>) {
    let ids = |list: &[IssueRef]| list.iter().map(ToString::to_string).collect::<Vec<_>>();
    let Some(ranking) = rank(graph) else {
        return;
    };
    let batch = select(graph, &ranking, capacities);
    let scores: Map<String, Value> = ranking
        .scores
        .iter()
        .map(|(id, score)| (id.to_string(), json!(score)))
        .collect();
    let skipped: Vec<Value> = batch
        .skipped
        .iter()
        .map(|(id, skip)| {
            let mut item = json!({"id": id.to_string(), "reason": skip.reason()});
            if let Skip::SemaphoreFull(names) = skip {
                item["semaphores"] = json!(names);
            }
            item
        })
        .collect();
    out.insert("ready".into(), json!(ids(&ranking.ready)));
    out.insert("scores".into(), Value::Object(scores));
    out.insert(
        "waves".into(),
        json!(ranking.waves.iter().map(|w| ids(w)).collect::<Vec<_>>()),
    );
    out.insert("critical_path".into(), json!(ids(&ranking.critical_path)));
    out.insert("batch".into(), json!(ids(&batch.selected)));
    out.insert("skipped".into(), json!(skipped));
    out.insert("unknown_capacity".into(), json!(batch.unknown_capacity));
}

/// The dispatchable subset of a ready set (Q2), as references.
type Dispatchable = BTreeSet<String>;

/// The crate's result in the form of corpus rule CC6, and the dispatchable
/// subset of its ready set when it reports a graph.
fn result_json(bundle_text: &str) -> Result<(Map<String, Value>, Option<Dispatchable>), String> {
    let bundle = load(bundle_text).map_err(|e| format!("bundle rejected: {e}"))?;
    let forge = RecordedForge::new(&bundle.observations);
    let mut out = Map::new();
    let outcome = match plan(&bundle.parameters, &forge) {
        Ok(outcome) => outcome,
        Err(missing) => {
            // OB5: the bundle is unusable; `missing` is the slot reported (OB16).
            out.insert("outcome".into(), json!("unusable"));
            out.insert("missing".into(), slot_path(&missing.what)?);
            return Ok((out, None));
        }
    };
    let (name, findings, graph) = match &outcome {
        Outcome::Rejected(_) => ("rejected", None, None),
        Outcome::Incomplete { unavailable } => {
            out.insert("unavailable".into(), json!(unavailable));
            ("incomplete", None, None)
        }
        Outcome::Invalid { findings, graph } => ("invalid", Some(findings), graph.as_ref()),
        Outcome::Planned { findings, graph } => ("planned", Some(findings), Some(graph)),
    };
    out.insert("outcome".into(), json!(name));
    if let Some(findings) = findings {
        let findings = findings
            .iter()
            .map(|f| {
                let mut finding = json!({"subject": f.subject.to_string(), "rule": f.label()});
                if let Some(concerns) = &f.concerns {
                    finding["concerns"] = json!(concerns.to_string());
                }
                finding
            })
            .collect();
        out.insert("findings".into(), sorted(findings));
    }
    if let Some(graph) = graph {
        graph_json(graph, &mut out);
        ranking_json(graph, &bundle.parameters.capacities, &mut out);
    }
    let dispatchable = graph.map(|g| g.dispatchable().iter().map(ToString::to_string).collect());
    Ok((out, dispatchable))
}

/// The path from `observations` to a slot the bundle lacks (CC6), from the
/// text `RecordedForge` gives it.
fn slot_path(what: &str) -> Result<Value, String> {
    let path: Vec<&str> = if what == "the listing of the open home issues" {
        vec!["home_open_issues"]
    } else if what == "the open home pull requests" {
        vec!["home_open_pull_requests"]
    } else if let Some(reference) = what.strip_prefix("the issue ") {
        vec!["issues", reference]
    } else if let Some(reference) = what.strip_prefix("the body of ") {
        vec!["issues", reference, "value", "body"]
    } else if let Some(repo) = what.strip_prefix("the CODEOWNERS of ") {
        vec!["codeowners", repo]
    } else if let Some((login, repo)) = what
        .strip_prefix("the permission of ")
        .and_then(|rest| rest.split_once(" on "))
    {
        vec!["permissions", repo, login]
    } else {
        return Err(format!("no slot of a bundle is {what:?}"));
    };
    Ok(json!(path))
}

/// Q2: in a normative planned case, every member of the expected batch is
/// dispatchable: ready, not opaque, not blocked. The member `batch` is also
/// compared with the batch rule B5 selects.
fn batch_not_dispatchable(
    expected: &Map<String, Value>,
    dispatchable: Option<&Dispatchable>,
) -> Vec<String> {
    if expected.get("outcome") != Some(&json!("planned")) {
        return Vec::new();
    }
    let Some(batch) = expected.get("batch").and_then(Value::as_array) else {
        return Vec::new();
    };
    batch
        .iter()
        .filter_map(Value::as_str)
        .filter(|id| !dispatchable.is_some_and(|d| d.contains(*id)))
        .map(|id| format!("batch: {id} is not dispatchable (Q2)"))
        .collect()
}

/// Brings a member of an expected result into the form it is compared in:
/// `findings` as a set.
fn comparable(member: &str, value: &Value) -> Value {
    match (member, value) {
        ("findings", Value::Array(items)) => sorted(items.clone()),
        _ => value.clone(),
    }
}

/// CC8 for a normative case: every member the expected result holds equals
/// the actual one.
fn normative_mismatch(expected: &Map<String, Value>, actual: &Map<String, Value>) -> Vec<String> {
    let invalid = expected.get("outcome") == Some(&json!("invalid"));
    expected
        .iter()
        .filter(|(member, _)| !(invalid && GRAPH.contains(&member.as_str())))
        .filter_map(|(member, want)| {
            let want = comparable(member, want);
            let got = actual.get(member).map(|v| comparable(member, v));
            (got.as_ref() != Some(&want)).then(|| {
                format!(
                    "{member}: expected {want}, got {}",
                    got.map_or_else(|| "nothing".to_owned(), |g| g.to_string())
                )
            })
        })
        .collect()
}

/// A characterisation case: the members of the actual result are exactly
/// those of the expected result, and equal.
fn exact_mismatch(expected: &Map<String, Value>, actual: &Map<String, Value>) -> Vec<String> {
    let covered = |m: &Map<String, Value>| -> BTreeSet<String> { m.keys().cloned().collect() };
    let (want, got) = (covered(expected), covered(actual));
    let mut problems: Vec<String> = want
        .symmetric_difference(&got)
        .map(|m| format!("{m}: present in only one of expected and actual"))
        .collect();
    problems.extend(normative_mismatch_all(expected, actual, &want));
    problems
}

fn normative_mismatch_all(
    expected: &Map<String, Value>,
    actual: &Map<String, Value>,
    members: &BTreeSet<String>,
) -> Vec<String> {
    members
        .iter()
        .filter_map(|member| {
            let want = comparable(member, &expected[member]);
            let got = actual.get(member).map(|v| comparable(member, v));
            (got.as_ref().is_some_and(|g| *g != want)).then(|| {
                format!(
                    "{member}: expected {want}, got {}",
                    got.map_or_else(String::new, |g| g.to_string())
                )
            })
        })
        .collect()
}

fn case_names() -> Vec<String> {
    let mut names: Vec<String> = fs::read_dir(corpus_dir())
        .expect("the vendored corpus is present")
        .map(|e| {
            e.expect("directory entry")
                .file_name()
                .into_string()
                .expect("UTF-8 name")
        })
        .collect();
    names.sort();
    names
}

#[test]
fn every_graph_case_of_the_corpus() {
    let names = case_names();
    assert!(!names.is_empty(), "no graph cases found");
    let mut failures = Vec::new();
    let (mut normative, mut twins, mut census) = (0, 0, 0);
    for name in &names {
        let dir = corpus_dir().join(name);
        let case = read_json(&dir.join("case.json"));
        let bundle_text = fs::read_to_string(dir.join("bundle.json")).expect("bundle.json");
        match (case["kind"].as_str(), case["normative_case"].is_string()) {
            (Some("normative"), _) => normative += 1,
            (Some("characterisation"), true) => twins += 1,
            (Some("characterisation"), false) => census += 1,
            _ => {}
        }
        let (actual, dispatchable) = match result_json(&bundle_text) {
            Ok(result) => result,
            Err(why) => {
                failures.push(format!("{name}: {why}"));
                continue;
            }
        };
        let problems = match (case["kind"].as_str(), case["normative_case"].as_str()) {
            (Some("normative"), _) => {
                let expected = read_json(&dir.join("expected.json"));
                let expected = expected.as_object().expect("object");
                let mut problems = normative_mismatch(expected, &actual);
                problems.extend(batch_not_dispatchable(expected, dispatchable.as_ref()));
                problems
            }
            (Some("characterisation"), Some(twin)) => {
                let twin_name = twin.strip_prefix("graph/").expect("a graph case");
                let twin_dir = corpus_dir().join(twin_name);
                assert_eq!(
                    read_json(&twin_dir.join("bundle.json")),
                    read_json(&dir.join("bundle.json")),
                    "{name}: the twin's input differs from its normative case's"
                );
                let expected = read_json(&twin_dir.join("expected.json"));
                normative_mismatch(expected.as_object().expect("object"), &actual)
            }
            (Some("characterisation"), None) => {
                // CC6: only a normative case states the unavailable slot
                // reported; the Python reports none.
                let mut actual = actual;
                actual.remove("unavailable");
                let expected = read_json(&dir.join("expected.json"));
                exact_mismatch(expected.as_object().expect("object"), &actual)
            }
            (kind, _) => vec![format!("unknown case kind {kind:?}")],
        };
        if !problems.is_empty() {
            failures.push(format!("{name}:\n    {}", problems.join("\n    ")));
        }
    }
    println!(
        "graph cases: {} ({normative} normative, {twins} --python twins, {census} other characterisation); {} failing",
        names.len(),
        failures.len()
    );
    assert_eq!(normative + twins + census, names.len());
    assert!(
        failures.is_empty(),
        "{} of {} graph cases fail:\n{}",
        failures.len(),
        names.len(),
        failures.join("\n")
    );
}
