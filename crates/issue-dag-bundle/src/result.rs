//! The result of a run in the form of corpus rule CC6
//! (`tests/fixtures/issue-dag/corpus/README.md`): the outcome, the findings,
//! the graph, its ranking and its batch, as JSON.
//!
//! The form is the specification's, not a tool's, so a result written here
//! can be compared with a corpus case and with another planner's. Lists
//! that CC6 makes sets are written in a fixed order, so that one outcome
//! always serialises to the same bytes.

use std::collections::{BTreeMap, BTreeSet};

use issue_dag_core::{Edge, Graph, IssueRef, Outcome, Skip, rank, select};
use serde_json::{Map, Value, json};

/// A list in a fixed order: objects by their `id`, or by `from`, `to` and
/// `status`, or by `subject`, `rule` and `concerns`; then by JSON text.
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
    let refs =
        |set: &BTreeSet<IssueRef>| sorted(set.iter().map(|r| json!(r.to_string())).collect());
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

/// The result of a run as corpus rule CC6 writes it. `capacities` are the
/// run's (bundle rule OB3), which the batch reads.
///
/// An incomplete or rejected run has only `outcome` (profile rule F2).
#[must_use]
pub fn outcome_json(outcome: &Outcome, capacities: &BTreeMap<String, u64>) -> Map<String, Value> {
    let mut out = Map::new();
    let (name, findings, graph) = match outcome {
        Outcome::Rejected(_) => ("rejected", None, None),
        Outcome::Incomplete { .. } => ("incomplete", None, None),
        Outcome::Invalid {
            findings, graph, ..
        } => ("invalid", Some(findings), graph.as_ref()),
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
        ranking_json(graph, capacities, &mut out);
    }
    out
}

/// A list of `findings`, or of any CC6 member that is a set, in the order
/// [`outcome_json`] writes it, so that two results compare as sets.
#[must_use]
pub fn in_result_order(items: Vec<Value>) -> Value {
    sorted(items)
}
