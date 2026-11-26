//! Renders a plan to the JSON result lines the Taskalisk skill reads.
//!
//! The messages are `taskalisk.plan`, `taskalisk.frontier_node`,
//! `taskalisk.batch`, `taskalisk.node`, `taskalisk.wave`, `taskalisk.edge`
//! and `taskalisk.finding` of `docs/topics/output/README.md`
//! (flyingrobots/taskalisk#58), in its line order, for the outcome of an
//! `issue-dag-planning/2` run, ranked by [`rank`] and batched by [`select`].
//!
//! A line is the message as the Python compiler hands it to the Parley
//! writer: `event`, `_schema` and the message's fields, without the writer's
//! envelope (`t`, `seq`, `run`), which the command line adds
//! (flyingrobots/taskalisk#31). Each line is one compact JSON object with
//! its keys in sorted order and a line feed, so equal plans give identical
//! bytes. Nothing here reads or writes anything.
//!
//! # Fields the core's result does not hold
//!
//! The renderer writes only what the run's parameters, its outcome, the
//! ranking and the batch determine. These fields of the schemas are left
//! out, never made up:
//!
//! - `taskalisk.plan`: `artifact_hash` (the hash of the 1.x result document,
//!   which holds every field below); `source.trust.codeowners` and
//!   `codeowners_teams_not_expanded` when the policy reads CODEOWNERS (the
//!   persons and teams each file named).
//! - `taskalisk.frontier_node`, `taskalisk.node`: `title`, `url`, `type`,
//!   `workstream`, `size_hours`, `linked_open_prs`, `recoverable_branches`.
//! - `taskalisk.batch` members: `title`, `url`, `workstream`.
//! - `taskalisk.finding`: the `title` (and for `issue.unmodeled` the `url`)
//!   of a detail; for `issue.untrusted` the message and the detail's `url`,
//!   `state`, `author`, `reasons` and `referenced_by`; for
//!   `pull_request.untrusted` the message and every detail but `number`.
//!   A `frontmatter.violation` or `frontmatter.warning` carries the core's
//!   fixed message for its rule, one line per rule.

use std::collections::{BTreeMap, BTreeSet};

use issue_dag_core::{
    Batch, Finding, Graph, Identity, IssueRef, NodeStatus, Outcome, Parameters, Ranking, Severity,
    Skip, rank, select,
};
use serde_json::{Map, Value, json};

/// The version of every message this module writes.
pub const SCHEMA_VERSION: &str = "1.0.0";

/// The edge density band the plan's metrics judge (1.x).
const DENSITY_BAND: (f64, f64) = (0.01, 0.50);

/// The weights of the score terms (rule K5).
const WEIGHTS: [(&str, u64); 5] = [
    ("in_flight", 1000),
    ("parked", 500),
    ("descendants", 100),
    ("critical_path_depth", 10),
    ("out_degree", 1),
];

/// What the adapters read beside the plan, for display (stub).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Display {
    /// Issue titles.
    pub titles: BTreeMap<IssueRef, String>,
    /// Issue URLs.
    pub urls: BTreeMap<IssueRef, String>,
    /// Pull request URLs.
    pub pull_request_urls: BTreeMap<u64, String>,
    /// Recoverable branches.
    pub recoverable_branches: BTreeMap<IssueRef, Vec<String>>,
    /// CODEOWNERS persons.
    pub codeowners: BTreeMap<String, Vec<String>>,
    /// CODEOWNERS teams.
    pub codeowners_teams_not_expanded: BTreeMap<String, Vec<String>>,
}

/// Why a run has no result lines.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NotRendered {
    /// The run was rejected (rule I2): a usage error, not a plan.
    Rejected,
    /// A required observation was unavailable (rule F2): an error, not a
    /// plan.
    Incomplete,
    /// The outcome reports a graph that cannot be ranked. A run never does.
    Unranked,
    /// The score terms of a node do not sum to its score. A run never does.
    ScoreTerms(IssueRef),
}

/// The result lines of a plan, as text: one JSON object per line.
///
/// # Errors
///
/// [`NotRendered`] when the run has no plan to render.
pub fn render(
    parameters: &Parameters,
    outcome: &Outcome,
    _display: Option<&Display>,
) -> Result<String, NotRendered> {
    let mut text = String::new();
    for line in lines(parameters, outcome)? {
        text.push_str(&line.to_string());
        text.push('\n');
    }
    Ok(text)
}

/// The result lines of a plan, in the order they are written.
///
/// # Errors
///
/// [`NotRendered`] when the run has no plan to render.
pub fn lines(parameters: &Parameters, outcome: &Outcome) -> Result<Vec<Value>, NotRendered> {
    let (findings, graph) = match outcome {
        Outcome::Rejected(_) => return Err(NotRendered::Rejected),
        Outcome::Incomplete { .. } => return Err(NotRendered::Incomplete),
        Outcome::Invalid { findings, graph } => (findings, graph.as_ref()),
        Outcome::Planned { findings, graph } => (findings, Some(graph)),
    };
    let report = Report::of(findings);
    let compiled = match graph {
        Some(graph) => {
            let ranking = rank(graph).ok_or(NotRendered::Unranked)?;
            let batch = select(graph, &ranking, &parameters.capacities);
            Some(Compiled::of(graph, ranking, batch)?)
        }
        None => None,
    };

    let mut out = vec![plan_line(parameters, &report, compiled.as_ref())];
    if let Some(c) = &compiled {
        out.extend(c.frontier_lines());
        out.push(c.batch_line());
        out.extend(c.node_lines());
        out.extend(c.wave_lines());
        out.extend(c.edge_lines());
    }
    out.extend(finding_lines(&report, graph, compiled.as_ref()));
    Ok(out)
}

/// One message: its fields, its event and its schema.
fn message(name: &str, mut fields: Map<String, Value>) -> Value {
    fields.insert("event".into(), json!(name));
    fields.insert(
        "_schema".into(),
        json!({"id": format!("taskalisk.{name}"), "version": SCHEMA_VERSION}),
    );
    Value::Object(fields)
}

fn object(value: Value) -> Map<String, Value> {
    match value {
        Value::Object(map) => map,
        _ => Map::new(),
    }
}

/// References as text, in the order given.
fn texts<'a>(ids: impl IntoIterator<Item = &'a IssueRef>) -> Vec<String> {
    ids.into_iter().map(ToString::to_string).collect()
}

/// References as text, sorted as text (the 1.x order).
fn sorted_texts<'a>(ids: impl IntoIterator<Item = &'a IssueRef>) -> Vec<String> {
    let mut out = texts(ids);
    out.sort();
    out
}

/// The findings of a run, by what they mean for the plan line.
struct Report<'a> {
    /// G4: the nodes on or behind a cycle.
    cyclic: Vec<&'a Finding>,
    /// X3: the unknown prerequisites.
    unknown: Vec<&'a Finding>,
    /// Every other violation.
    violations: Vec<&'a Finding>,
    /// The warnings.
    warnings: Vec<&'a Finding>,
}

impl<'a> Report<'a> {
    fn of(findings: &'a BTreeSet<Finding>) -> Self {
        let mut report = Self {
            cyclic: Vec::new(),
            unknown: Vec::new(),
            violations: Vec::new(),
            warnings: Vec::new(),
        };
        for f in findings {
            match (f.severity, f.label()) {
                (Severity::Warning, _) => report.warnings.push(f),
                (Severity::Error, "G4") => report.cyclic.push(f),
                (Severity::Error, "X3") => report.unknown.push(f),
                (Severity::Error, _) => report.violations.push(f),
            }
        }
        report
    }
}

fn plan_line(parameters: &Parameters, report: &Report, compiled: Option<&Compiled>) -> Value {
    let mut error_codes = Vec::new();
    let outcome = if compiled.is_some() {
        "compiled"
    } else if report.cyclic.is_empty() {
        error_codes.push("graph.unresolved_prerequisites");
        "unresolved"
    } else {
        error_codes.push("graph.cycle");
        "cycle"
    };
    if !report.violations.is_empty() {
        error_codes.push("frontmatter.invalid");
    }
    let violating: BTreeSet<&IssueRef> = report.violations.iter().map(|f| &f.subject).collect();
    let mut fields = object(json!({
        "mode": "github",
        "outcome": outcome,
        "ok": compiled.is_some() && error_codes.is_empty(),
        "error_codes": error_codes,
        "source": source(parameters),
        "violating_issues": violating.len(),
        "relationships": {"compared": false},
    }));
    if let Some(c) = compiled {
        fields.insert("metrics".into(), c.metrics());
        fields.insert("open_frontier_count".into(), json!(c.ranking.ready.len()));
        fields.insert("frontier".into(), json!(texts(&c.ranking.ready)));
        fields.insert("batch".into(), json!(texts(&c.batch.selected)));
    }
    message("plan", fields)
}

/// The plan line's `source`: the home repository, the roots as given and
/// the trust in force.
fn source(parameters: &Parameters) -> Value {
    let lower = |items: Vec<String>| -> Vec<String> {
        let set: BTreeSet<String> = items.into_iter().map(|s| s.to_lowercase()).collect();
        set.into_iter().collect()
    };
    let scope = &parameters.read_scope;
    let mut trust = object(json!({
        "owners": lower(scope.owners.iter().cloned().collect()),
        "repos": lower(scope.repositories.iter().map(ToString::to_string).collect()),
        "logins": lower(parameters.trust.logins.iter().map(|l| login(l)).collect()),
    }));
    if !parameters.trust.codeowners {
        trust.insert("codeowners".into(), Value::Null);
        trust.insert("codeowners_teams_not_expanded".into(), json!({}));
    }
    json!({
        "kind": "issue-frontmatter",
        "schema": "issue-dag/2",
        "repository": parameters.home.to_string(),
        "roots": parameters.roots,
        "trust": trust,
    })
}

/// An allowlist entry as the identity it names (rule AD3): a bot's as
/// `bot:<name>`, which is how 1.x writes it, a person's as the name.
fn login(entry: &str) -> String {
    let identity = Identity::of_entry(entry);
    if identity.bot {
        format!("bot:{}", identity.name)
    } else {
        identity.name
    }
}

/// A reported graph with its ranking, its batch and what the lines derive
/// from them.
struct Compiled<'a> {
    graph: &'a Graph,
    ranking: Ranking,
    batch: Batch,
    /// The open nodes, sorted as text.
    open: Vec<&'a IssueRef>,
    /// The children of each open node in the graph, redundant edges
    /// included, sorted as text.
    raw_children: BTreeMap<&'a IssueRef, Vec<&'a IssueRef>>,
    /// The children in the reduced graph (G5), sorted as text.
    children: BTreeMap<&'a IssueRef, Vec<&'a IssueRef>>,
    /// The parents in the reduced graph, sorted as text.
    parents: BTreeMap<&'a IssueRef, Vec<&'a IssueRef>>,
    /// The open nodes each node transitively unblocks (K1).
    descendants: BTreeMap<&'a IssueRef, BTreeSet<&'a IssueRef>>,
    /// The longest remaining chain from each node, itself counted (K2).
    depth: BTreeMap<&'a IssueRef, u64>,
    /// The wave of each open node (K7).
    wave: BTreeMap<&'a IssueRef, usize>,
}

impl<'a> Compiled<'a> {
    fn of(graph: &'a Graph, ranking: Ranking, batch: Batch) -> Result<Self, NotRendered> {
        let mut open: Vec<&IssueRef> = graph
            .nodes
            .iter()
            .filter(|(_, n)| !n.complete)
            .map(|(id, _)| id)
            .collect();
        open.sort_by_key(ToString::to_string);
        let by_text = |list: &mut Vec<&IssueRef>| list.sort_by_key(ToString::to_string);
        let mut raw_children: BTreeMap<&IssueRef, Vec<&IssueRef>> = BTreeMap::new();
        let mut children: BTreeMap<&IssueRef, Vec<&IssueRef>> = BTreeMap::new();
        let mut parents: BTreeMap<&IssueRef, Vec<&IssueRef>> = BTreeMap::new();
        for edge in &graph.edges {
            raw_children.entry(&edge.from).or_default().push(&edge.to);
            if !graph.redundant.contains(edge) {
                children.entry(&edge.from).or_default().push(&edge.to);
                parents.entry(&edge.to).or_default().push(&edge.from);
            }
        }
        for list in raw_children
            .values_mut()
            .chain(children.values_mut())
            .chain(parents.values_mut())
        {
            by_text(list);
        }
        let mut wave = BTreeMap::new();
        for (k, ids) in ranking.waves.iter().enumerate() {
            for id in ids {
                if let Some((key, _)) = graph.nodes.get_key_value(id) {
                    wave.insert(key, k);
                }
            }
        }
        // K1 and K2 from the last wave back: every child is in a later wave.
        let mut descendants: BTreeMap<&IssueRef, BTreeSet<&IssueRef>> = BTreeMap::new();
        let mut depth: BTreeMap<&IssueRef, u64> = BTreeMap::new();
        let mut by_wave: Vec<&IssueRef> = wave.keys().copied().collect();
        by_wave.sort_by_key(|id| std::cmp::Reverse(wave[id]));
        for u in by_wave {
            let mut below = BTreeSet::new();
            let mut longest = 0;
            for &c in children.get(u).map_or(&[][..], Vec::as_slice) {
                below.insert(c);
                below.extend(descendants.get(c).into_iter().flatten().copied());
                longest = longest.max(depth.get(c).copied().unwrap_or(0));
            }
            descendants.insert(u, below);
            depth.insert(u, longest + 1);
        }
        let compiled = Self {
            graph,
            ranking,
            batch,
            open,
            raw_children,
            children,
            parents,
            descendants,
            depth,
            wave,
        };
        for &id in &compiled.open {
            let total: u64 = compiled.terms(id).iter().map(|(_, v, w)| v * w).sum();
            if compiled.ranking.scores.get(id) != Some(&total) {
                return Err(NotRendered::ScoreTerms(id.clone()));
            }
        }
        Ok(compiled)
    }

    fn children_of(&self, id: &IssueRef) -> &[&'a IssueRef] {
        self.children.get(id).map_or(&[], Vec::as_slice)
    }

    fn parents_of(&self, id: &IssueRef) -> &[&'a IssueRef] {
        self.parents.get(id).map_or(&[], Vec::as_slice)
    }

    fn status(&self, id: &IssueRef) -> NodeStatus {
        self.graph
            .nodes
            .get(id)
            .and_then(|n| n.status)
            .unwrap_or(NodeStatus::Open)
    }

    /// The score terms of a node (K3 to K5): name, value and weight.
    fn terms(&self, id: &IssueRef) -> [(&'static str, u64, u64); 5] {
        let status = self.status(id);
        let in_flight = matches!(
            status,
            NodeStatus::InProgress | NodeStatus::Wip | NodeStatus::InReview
        );
        let values = [
            u64::from(in_flight),
            u64::from(status == NodeStatus::Parked),
            self.descendants.get(id).map_or(0, |d| d.len() as u64),
            self.depth.get(id).copied().unwrap_or(1),
            self.children_of(id).len() as u64,
        ];
        let mut out = [("", 0, 0); 5];
        for (slot, ((name, weight), value)) in out.iter_mut().zip(WEIGHTS.iter().zip(values)) {
            *slot = (name, value, *weight);
        }
        out
    }

    fn score(&self, id: &IssueRef) -> u64 {
        self.ranking.scores.get(id).copied().unwrap_or(0)
    }

    fn metrics(&self) -> Value {
        let n = self.open.len();
        let raw = self.graph.edges.len();
        let reduced = raw - self.graph.redundant.len();
        let density = if n > 1 {
            #[expect(clippy::cast_precision_loss, reason = "edge counts are far below 2^52")]
            let ratio = reduced as f64 / ((n * (n - 1)) as f64 / 2.0);
            // Rounded to four places as Python's round() does: correctly, on
            // the decimal value.
            format!("{ratio:.4}").parse().unwrap_or(ratio)
        } else {
            0.0
        };
        let isolated: Vec<String> = self
            .open
            .iter()
            .filter(|id| self.children_of(id).is_empty() && self.parents_of(id).is_empty())
            .map(ToString::to_string)
            .collect();
        json!({
            "merged_count": self.graph.nodes.values().filter(|n| n.complete).count(),
            "open_node_count": n,
            "raw_open_edge_count": raw,
            "reduced_open_edge_count": reduced,
            "transitive_redundant_edges_removed_count": self.graph.redundant.len(),
            "edge_density": density,
            "edge_density_band_ok": n <= 1 || (DENSITY_BAND.0..=DENSITY_BAND.1).contains(&density),
            "max_parallel_width": self.ranking.waves.iter().map(Vec::len).max().unwrap_or(0),
            "critical_path_length": self.ranking.critical_path.len(),
            "critical_path": texts(&self.ranking.critical_path),
            "isolated_open_node_count": isolated.len(),
            "isolated_open_nodes": isolated,
        })
    }

    /// The fields of a node's line.
    fn node_fields(&self, id: &IssueRef) -> Map<String, Value> {
        let node = &self.graph.nodes[id];
        let completed = self
            .graph
            .satisfied
            .iter()
            .filter(|e| e.to == *id)
            .map(|e| &e.from);
        let wave = self.wave.get(id).copied().unwrap_or(0);
        object(json!({
            "id": id.to_string(),
            "milestone": null,
            "in_filter": true,
            "status": self.status(id).as_str(),
            "derived_status": if wave == 0 { "open-frontier" } else { "blocked" },
            "completed_parents": sorted_texts(completed),
            "open_parents": texts(self.parents_of(id).iter().copied()),
            "directly_unlocks": texts(self.children_of(id).iter().copied()),
            "transitive_unblocks_count": self.descendants.get(id).map_or(0, BTreeSet::len),
            "critical_path_remaining_depth": self.depth.get(id).copied().unwrap_or(1),
            "priority_score": self.score(id),
            "holds": node.holds,
            "meters": meters(id, self.graph),
            "opaque": node.opaque,
            "untrusted": node.untrusted,
        }))
    }

    fn frontier_lines(&self) -> Vec<Value> {
        self.ranking
            .ready
            .iter()
            .enumerate()
            .map(|(i, id)| {
                let mut fields = self.node_fields(id);
                let terms: Map<String, Value> = self
                    .terms(id)
                    .iter()
                    .map(|&(name, value, weight)| {
                        let points = value * weight;
                        (
                            name.to_owned(),
                            json!({"value": value, "weight": weight, "points": points}),
                        )
                    })
                    .collect();
                fields.insert("rank".into(), json!(i + 1));
                fields.insert("wave".into(), json!(0));
                fields.insert(
                    "score".into(),
                    json!({"total": self.score(id), "terms": terms}),
                );
                message("frontier_node", fields)
            })
            .collect()
    }

    fn batch_line(&self) -> Value {
        let members: Vec<Value> = self
            .batch
            .selected
            .iter()
            .map(|id| {
                json!({
                    "id": id.to_string(),
                    "priority_score": self.score(id),
                    "holds": self.graph.nodes.get(id).map(|n| &n.holds),
                    "meters": meters(id, self.graph),
                })
            })
            .collect();
        let skipped: Vec<Value> = self
            .batch
            .skipped
            .iter()
            .map(|(id, skip)| {
                let reason = match skip {
                    Skip::HoldsConflict => skip.reason().to_owned(),
                    Skip::SemaphoreFull(names) => format!(
                        "{}: {}",
                        skip.reason(),
                        names.iter().cloned().collect::<Vec<_>>().join(", ")
                    ),
                };
                json!({"id": id.to_string(), "reason": reason})
            })
            .collect();
        message(
            "batch",
            object(json!({
                "members": members,
                "skipped": skipped,
                "semaphores_with_unknown_capacity_treated_as_1": self.batch.unknown_capacity,
            })),
        )
    }

    fn node_lines(&self) -> Vec<Value> {
        let mut out = Vec::new();
        for (k, ids) in self.ranking.waves.iter().enumerate().skip(1) {
            for id in ids {
                let mut fields = self.node_fields(id);
                fields.insert("wave".into(), json!(k));
                out.push(message("node", fields));
            }
        }
        out
    }

    fn wave_lines(&self) -> Vec<Value> {
        self.ranking
            .waves
            .iter()
            .enumerate()
            .map(|(k, ids)| {
                message(
                    "wave",
                    object(json!({"wave": k, "label": format!("Wave {k}"), "ids": texts(ids)})),
                )
            })
            .collect()
    }

    fn edge_lines(&self) -> Vec<Value> {
        let mut out = Vec::new();
        for &u in &self.open {
            for &v in self.children_of(u) {
                out.push(message(
                    "edge",
                    object(json!({
                        "from": u.to_string(),
                        "to": v.to_string(),
                        "evidence": format!("frontmatter: {v} .blocked_by {u}"),
                    })),
                ));
            }
        }
        out
    }

    /// The redundant edges (G5), each with the first child of its source,
    /// as text, through which it is implied.
    fn redundant(&self) -> Vec<(&'a IssueRef, &'a IssueRef, &'a IssueRef)> {
        let mut out = Vec::new();
        for &u in &self.open {
            let raw = self.raw_children.get(u).map_or(&[][..], Vec::as_slice);
            for &v in raw {
                let redundant = self
                    .graph
                    .redundant
                    .iter()
                    .any(|e| e.from == *u && e.to == *v);
                if !redundant {
                    continue;
                }
                let via = raw
                    .iter()
                    .copied()
                    .find(|&w| w != v && self.descendants.get(w).is_some_and(|d| d.contains(v)));
                if let Some(w) = via {
                    out.push((u, v, w));
                }
            }
        }
        out
    }
}

/// A node's meter claims as written.
fn meters(id: &IssueRef, graph: &Graph) -> Value {
    let claims = graph.nodes.get(id).map_or(&[][..], |n| n.meters.as_slice());
    json!(
        claims
            .iter()
            .map(|m| json!({"name": m.name, "slots": m.slots}))
            .collect::<Vec<_>>()
    )
}

fn finding(
    code: &str,
    subject: Option<String>,
    text: Option<String>,
    detail: Option<Value>,
) -> Value {
    let mut fields = Map::new();
    fields.insert("code".into(), json!(code));
    if let Some(subject) = subject {
        fields.insert("subject".into(), json!(subject));
    }
    if let Some(text) = text {
        fields.insert("message".into(), json!(text));
    }
    if let Some(detail) = detail {
        fields.insert("detail".into(), detail);
    }
    message("finding", fields)
}

/// Every finding, in the 1.x order of codes.
fn finding_lines(
    report: &Report,
    graph: Option<&Graph>,
    compiled: Option<&Compiled>,
) -> Vec<Value> {
    let mut out = Vec::new();
    if let Some(graph) = graph {
        out.extend(graph_findings(graph));
    }
    for (code, list) in [
        ("frontmatter.violation", &report.violations),
        ("frontmatter.warning", &report.warnings),
    ] {
        for f in list {
            out.push(finding(
                code,
                Some(f.subject.to_string()),
                Some(f.message.to_owned()),
                None,
            ));
        }
    }
    if let Some(c) = compiled {
        for (u, v, w) in c.redundant() {
            out.push(finding(
                "edge.redundant",
                Some(format!("{u}->{v}")),
                Some(format!("{u} -> {v} is implied via {w}")),
                Some(json!({"from": u.to_string(), "to": v.to_string(), "implied_via": w.to_string()})),
            ));
        }
    }
    for f in &report.unknown {
        let Some(prerequisite) = &f.concerns else {
            continue;
        };
        out.push(finding(
            "prerequisite.unknown",
            Some(f.subject.to_string()),
            Some(format!(
                "{} names {prerequisite}, which is neither open nor completed",
                f.subject
            )),
            Some(json!({"node": f.subject.to_string(), "unknown_prerequisite": prerequisite.to_string()})),
        ));
    }
    for id in sorted_texts(report.cyclic.iter().map(|f| &f.subject)) {
        out.push(finding(
            "graph.cyclic_node",
            Some(id.clone()),
            Some(format!("{id} is on or behind a cycle of hard edges")),
            None,
        ));
    }
    out
}

/// The findings a graph lists (rule W1): containers, unmodeled, untrusted
/// and opaque issues, untrusted pull requests and not-planned blockers.
fn graph_findings(graph: &Graph) -> Vec<Value> {
    let mut out = Vec::new();
    for id in graph.containers.keys() {
        out.push(finding(
            "container.excluded",
            Some(id.to_string()),
            Some(format!(
                "{id} is a container: its children are nodes and it is not"
            )),
            Some(json!({"id": id.to_string(), "number": id.number()})),
        ));
    }
    for id in &graph.unmodeled {
        out.push(finding(
            "issue.unmodeled",
            Some(id.to_string()),
            Some(format!(
                "{id} is an open home issue without frontmatter; it is not a node"
            )),
            Some(json!({"id": id.to_string()})),
        ));
    }
    for id in &graph.untrusted {
        out.push(finding(
            "issue.untrusted",
            Some(id.to_string()),
            None,
            Some(json!({"id": id.to_string()})),
        ));
    }
    for number in &graph.untrusted_pull_requests {
        out.push(finding(
            "pull_request.untrusted",
            None,
            None,
            Some(json!({"number": number})),
        ));
    }
    for (id, node) in &graph.nodes {
        if !node.opaque || node.untrusted {
            continue;
        }
        let referenced_by = sorted_texts(
            graph
                .edges
                .iter()
                .chain(&graph.satisfied)
                .filter(|e| e.from == *id)
                .map(|e| &e.to),
        );
        let blocks = if referenced_by.is_empty() {
            "nothing".to_owned()
        } else {
            referenced_by.join(", ")
        };
        out.push(finding(
            "issue.opaque",
            Some(id.to_string()),
            Some(format!(
                "{id} has no frontmatter; it blocks {blocks} until it closes"
            )),
            Some(json!({
                "id": id.to_string(),
                "state": if node.complete { "closed" } else { "open" },
                "referenced_by": referenced_by,
            })),
        ));
    }
    for edge in &graph.not_planned {
        out.push(finding(
            "parent.not_planned",
            Some(edge.from.to_string()),
            Some(format!(
                "{} closed as not planned and still satisfies the edge to {}; review it",
                edge.from, edge.to
            )),
            Some(json!({"parent": edge.from.to_string(), "child": edge.to.to_string()})),
        ));
    }
    out
}
