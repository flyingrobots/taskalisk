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
//! # What comes from where
//!
//! The run's parameters, its outcome, the ranking and the batch give every
//! field but those a [`Display`] input carries: the titles and URLs of
//! issues and pull requests, the recoverable branches, and the persons and
//! teams the CODEOWNERS files named. Without a display input those fields
//! are left out, never made up. The plan line's `artifact_hash` digests
//! the document the renderer emits (see [`lines`]).
//!
//! These are not rendered with or without a display input:
//!
//! - the message and every detail but the id or number of an
//!   `issue.untrusted` or `pull_request.untrusted` finding: the trust
//!   gate's reasons (flyingrobots/taskalisk#46);
//! - the findings about what discovery read, for a run whose edges form a
//!   cycle or name an unknown prerequisite: the core reports no graph for
//!   it, rule F3 (flyingrobots/taskalisk#44).
//!
//! A `frontmatter.violation` or `frontmatter.warning` carries the core's
//! fixed message for its rule, one line per rule.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt::Write as _;

use issue_dag_core::{
    Batch, Edge, Finding, Graph, Identity, IssueRef, NodeStatus, Outcome, Parameters, Ranking,
    Severity, Skip, Terms, rank, select,
};
use serde_json::{Map, Value, json};

use crate::sha256;

/// The version of every message this module writes.
pub const SCHEMA_VERSION: &str = "1.0.0";

/// The edge density band the plan's metrics judge (1.x).
const DENSITY_BAND: (f64, f64) = (0.01, 0.50);

/// The title 1.x gives an untrusted issue, whose own is never shown
/// (threat model C3).
const UNTRUSTED_TITLE: &str = "(untrusted issue)";

/// What the adapters read beside the observations the core plans from,
/// only to show it: never an input to the plan.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Display {
    /// The title of each issue, as GitHub returns it.
    pub titles: BTreeMap<IssueRef, String>,
    /// The URL of each issue.
    pub urls: BTreeMap<IssueRef, String>,
    /// The URL of each pull request of the home repository, by number.
    pub pull_request_urls: BTreeMap<u64, String>,
    /// The local branches that name each home issue; none when absent.
    pub recoverable_branches: BTreeMap<IssueRef, Vec<String>>,
    /// For each repository (`owner/name`), the persons its CODEOWNERS file
    /// named, when the policy reads CODEOWNERS.
    pub codeowners: BTreeMap<String, Vec<String>>,
    /// For each repository, the teams its CODEOWNERS file named, which are
    /// not expanded.
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
}

/// The result lines of a plan, as text: one JSON object per line.
///
/// # Errors
///
/// [`NotRendered`] when the run has no plan to render.
pub fn render(
    parameters: &Parameters,
    outcome: &Outcome,
    display: Option<&Display>,
) -> Result<String, NotRendered> {
    let mut text = String::new();
    for line in lines(parameters, outcome, display)? {
        text.push_str(&line.to_string());
        text.push('\n');
    }
    Ok(text)
}

/// The result lines of a plan, in the order they are written.
///
/// The plan line's `artifact_hash` is always written: the SHA-256 of the
/// result document the renderer emits, in the 1.x shape. It equals the
/// Python's when that document holds no intended difference and no gap
/// (`docs/topics/output/README.md`).
///
/// # Errors
///
/// [`NotRendered`] when the run has no plan to render.
pub fn lines(
    parameters: &Parameters,
    outcome: &Outcome,
    display: Option<&Display>,
) -> Result<Vec<Value>, NotRendered> {
    let (findings, graph) = match outcome {
        Outcome::Rejected(_) => return Err(NotRendered::Rejected),
        Outcome::Incomplete { .. } => return Err(NotRendered::Incomplete),
        Outcome::Invalid { findings, graph } => (findings, graph.as_ref()),
        Outcome::Planned { findings, graph } => (findings, Some(graph)),
    };
    let report = Report::of(findings);
    let shown = Shown { display };
    let compiled = match graph {
        Some(graph) => {
            let ranking = rank(graph).ok_or(NotRendered::Unranked)?;
            let batch = select(graph, &ranking, &parameters.capacities);
            Some(Compiled::of(graph, ranking, batch, &shown))
        }
        None => None,
    };
    let discovery = graph.map(|g| Discovery::of(g, &shown));

    let mut plan = plan_line(parameters, &report, compiled.as_ref(), display);
    let mut out = Vec::new();
    if let Some(c) = &compiled {
        out.extend(c.frontier_lines());
        out.push(c.batch_line());
        out.extend(c.node_lines());
        out.extend(c.wave_lines());
        out.extend(c.edge_lines());
    }
    out.extend(finding_lines(
        &report,
        discovery.as_ref(),
        compiled.as_ref(),
    ));

    let document = document(&plan, &report, discovery.as_ref(), compiled.as_ref());
    plan["artifact_hash"] = json!(sha256::hex(canonical(&document).as_bytes()));
    out.insert(0, plan);
    Ok(out)
}

/// The text 1.x hashes: keys sorted, compact separators, every character
/// past ASCII escaped as `\uXXXX`, and a line feed.
fn canonical(value: &Value) -> String {
    let mut out = String::new();
    // serde_json already escapes `"`, `\\` and the C0 controls as Python
    // does; every other character outside 0x20 to 0x7E is escaped here.
    for c in value.to_string().chars() {
        if (' '..='~').contains(&c) {
            out.push(c);
        } else {
            let mut units = [0_u16; 2];
            for unit in c.encode_utf16(&mut units) {
                let _ = write!(out, "\\u{unit:04x}");
            }
        }
    }
    out.push('\n');
    out
}

/// The display input, when given.
struct Shown<'a> {
    display: Option<&'a Display>,
}

impl Shown<'_> {
    /// Looks one value up.
    fn get<K: Ord, V: Clone>(
        &self,
        map: impl Fn(&Display) -> &BTreeMap<K, V>,
        key: &K,
    ) -> Option<V> {
        self.display.and_then(|d| map(d).get(key).cloned())
    }

    /// Adds an issue's title to an object, when shown; an untrusted
    /// issue's is never its own.
    fn title(&self, fields: &mut Map<String, Value>, id: &IssueRef, untrusted: bool) {
        if self.display.is_none() {
            return;
        }
        let title = if untrusted {
            Some(UNTRUSTED_TITLE.to_owned())
        } else {
            self.get(|d| &d.titles, id)
        };
        if let Some(title) = title {
            fields.insert("title".into(), json!(title));
        }
    }

    fn url(&self, fields: &mut Map<String, Value>, id: &IssueRef) {
        if let Some(url) = self.get(|d| &d.urls, id) {
            fields.insert("url".into(), json!(url));
        }
    }
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

fn plan_line(
    parameters: &Parameters,
    report: &Report,
    compiled: Option<&Compiled>,
    display: Option<&Display>,
) -> Value {
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
        "source": source(parameters, display),
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
fn source(parameters: &Parameters, display: Option<&Display>) -> Value {
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
    match (parameters.trust.codeowners, display) {
        (false, _) => {
            trust.insert("codeowners".into(), Value::Null);
            trust.insert("codeowners_teams_not_expanded".into(), json!({}));
        }
        (true, Some(d)) => {
            trust.insert("codeowners".into(), json!(d.codeowners));
            trust.insert(
                "codeowners_teams_not_expanded".into(),
                json!(d.codeowners_teams_not_expanded),
            );
        }
        (true, None) => {}
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
    /// The children in the reduced graph (G5), sorted as text.
    children: BTreeMap<&'a IssueRef, Vec<&'a IssueRef>>,
    /// The parents in the reduced graph, sorted as text.
    parents: BTreeMap<&'a IssueRef, Vec<&'a IssueRef>>,
    /// The wave of each open node (K7).
    wave: BTreeMap<&'a IssueRef, usize>,
    /// The completed prerequisites of each open node.
    completed: BTreeMap<&'a IssueRef, Vec<&'a IssueRef>>,
    /// The redundant edges with the node each is implied through.
    redundant: Vec<Value>,
    /// The 1.x node object of each open node.
    docs: BTreeMap<&'a IssueRef, Map<String, Value>>,
}

impl<'a> Compiled<'a> {
    fn of(graph: &'a Graph, ranking: Ranking, batch: Batch, shown: &Shown) -> Self {
        let mut open: Vec<&IssueRef> = graph
            .nodes
            .iter()
            .filter(|(_, n)| !n.complete)
            .map(|(id, _)| id)
            .collect();
        open.sort_by_cached_key(ToString::to_string);
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
            list.sort_by_cached_key(ToString::to_string);
        }
        let mut wave = BTreeMap::new();
        for (k, ids) in ranking.waves.iter().enumerate() {
            for id in ids {
                if let Some((key, _)) = graph.nodes.get_key_value(id) {
                    wave.insert(key, k);
                }
            }
        }
        let mut completed: BTreeMap<&IssueRef, Vec<&IssueRef>> = BTreeMap::new();
        for e in &graph.satisfied {
            completed.entry(&e.to).or_default().push(&e.from);
        }
        let redundant = redundant(graph, &open, &raw_children, &wave);
        let mut compiled = Self {
            graph,
            ranking,
            batch,
            open,
            children,
            parents,
            wave,
            completed,
            redundant,
            docs: BTreeMap::new(),
        };
        compiled.docs = compiled
            .open
            .iter()
            .map(|&id| (id, compiled.node_doc(id, shown)))
            .collect();
        compiled
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

    fn terms(&self, id: &IssueRef) -> Terms {
        self.ranking.terms.get(id).copied().unwrap_or_default()
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

    /// A node as 1.x writes it in its result document; its lines add their
    /// own fields.
    fn node_doc(&self, id: &IssueRef, shown: &Shown) -> Map<String, Value> {
        let node = &self.graph.nodes[id];
        let completed = self.completed.get(id).into_iter().flatten().copied();
        let wave = self.wave.get(id).copied().unwrap_or(0);
        let terms = self.terms(id);
        let (kind, workstream) = match node.task_type {
            Some(t) => (t.as_str(), t.as_str()),
            None if node.opaque => ("opaque", "unassigned"),
            None => ("task", "unassigned"),
        };
        let pulls: Vec<Value> = node
            .pull_requests
            .iter()
            .map(|p| {
                let mut pull = object(json!({"number": p.number, "isDraft": p.draft}));
                if let Some(url) = shown.get(|d| &d.pull_request_urls, &p.number) {
                    pull.insert("url".into(), json!(url));
                }
                Value::Object(pull)
            })
            .collect();
        let mut fields = object(json!({
            "id": id.to_string(),
            "type": kind,
            "workstream": workstream,
            "milestone": null,
            "in_filter": true,
            "status": self.status(id).as_str(),
            "derived_status": if wave == 0 { "open-frontier" } else { "blocked" },
            "linked_open_prs": pulls,
            "completed_parents": sorted_texts(completed),
            "open_parents": texts(self.parents_of(id).iter().copied()),
            "directly_unlocks": texts(self.children_of(id).iter().copied()),
            "transitive_unblocks_count": terms.descendants,
            "critical_path_remaining_depth": terms.critical_path_depth,
            "priority_score": self.score(id),
            "holds": node.holds,
            "meters": meters(id, self.graph),
            "opaque": node.opaque,
            "untrusted": node.untrusted,
            "size_hours": node.size_hours,
        }));
        if let Some(display) = shown.display {
            shown.title(&mut fields, id, node.untrusted);
            shown.url(&mut fields, id);
            let branches = display
                .recoverable_branches
                .get(id)
                .cloned()
                .unwrap_or_default();
            fields.insert("recoverable_branches".into(), json!(branches));
        }
        fields
    }

    fn frontier_lines(&self) -> Vec<Value> {
        self.ranking
            .ready
            .iter()
            .enumerate()
            .map(|(i, id)| {
                let mut fields = self.docs.get(id).cloned().unwrap_or_default();
                let terms: Map<String, Value> = self
                    .terms(id)
                    .points()
                    .iter()
                    .map(|&(name, value, weight, points)| {
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
                    json!({"total": self.terms(id).total(), "terms": terms}),
                );
                message("frontier_node", fields)
            })
            .collect()
    }

    /// The batch's members, as 1.x writes them.
    fn members(&self) -> Vec<Value> {
        self.batch
            .selected
            .iter()
            .map(|id| {
                let doc = self.docs.get(id).cloned().unwrap_or_default();
                let member: Map<String, Value> = doc
                    .into_iter()
                    .filter(|(k, _)| {
                        matches!(
                            k.as_str(),
                            "id" | "title"
                                | "url"
                                | "workstream"
                                | "priority_score"
                                | "holds"
                                | "meters"
                        )
                    })
                    .collect();
                Value::Object(member)
            })
            .collect()
    }

    fn skipped(&self) -> Vec<Value> {
        self.batch
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
            .collect()
    }

    fn batch_line(&self) -> Value {
        message(
            "batch",
            object(json!({
                "members": self.members(),
                "skipped": self.skipped(),
                "semaphores_with_unknown_capacity_treated_as_1": self.batch.unknown_capacity,
            })),
        )
    }

    fn node_lines(&self) -> Vec<Value> {
        let mut out = Vec::new();
        for (k, ids) in self.ranking.waves.iter().enumerate().skip(1) {
            for id in ids {
                let mut fields = self.docs.get(id).cloned().unwrap_or_default();
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

    /// The reduced edges, as 1.x writes them: by source, then target, as
    /// text.
    fn edges(&self) -> Vec<Value> {
        let mut out = Vec::new();
        for &u in &self.open {
            for &v in self.children_of(u) {
                out.push(json!({
                    "from": u.to_string(),
                    "to": v.to_string(),
                    "evidence": format!("frontmatter: {v} .blocked_by {u}"),
                }));
            }
        }
        out
    }

    fn edge_lines(&self) -> Vec<Value> {
        self.edges()
            .into_iter()
            .map(|e| message("edge", object(e)))
            .collect()
    }

    /// The redundant edges (G5), each with the node it is implied through.
    fn redundant(&self) -> Vec<Value> {
        self.redundant.clone()
    }

    /// The result document of a compiled plan, in the 1.x shape, as the
    /// renderer emits it.
    fn document(&self, plan: &Value, source: &Value, frontmatter: &Value) -> Value {
        let ranked = |ids: &[IssueRef]| -> Vec<Value> {
            ids.iter()
                .filter_map(|id| self.docs.get(id).cloned().map(Value::Object))
                .collect()
        };
        let waves: Map<String, Value> = self
            .ranking
            .waves
            .iter()
            .enumerate()
            .map(|(k, ids)| (format!("Wave {k}"), json!(ranked(ids))))
            .collect();
        json!({
            "ok": plan["ok"],
            "metrics": plan["metrics"],
            "edges": self.edges(),
            "transitive_redundant_edges_removed": self.redundant(),
            "soft_or_low_confidence_edges": [],
            "unknown_dependencies": [],
            "stale_merged_hints": [],
            "open_frontier_count": self.ranking.ready.len(),
            "open_frontier_ranked": ranked(&self.ranking.ready),
            "conflict_free_frontier_batch": self.members(),
            "batch_skipped": self.skipped(),
            "semaphores_with_unknown_capacity_treated_as_1": self.batch.unknown_capacity,
            "waves": waves,
            "source": source,
            "frontmatter": frontmatter,
        })
    }
}

/// The 1.x result's `source`: the plan line's, and what discovery read
/// (none when the run reports no graph).
fn document_source(plan: &Value, discovery: Option<&Discovery>) -> Value {
    let mut source = object(plan["source"].clone());
    let list = |pick: fn(&Discovery) -> &Vec<Value>| json!(discovery.map_or(&Vec::new(), pick));
    source.insert("containers_excluded".into(), list(|d| &d.containers));
    source.insert("unmodeled_open_issues".into(), list(|d| &d.unmodeled));
    source.insert("untrusted_issues".into(), list(|d| &d.untrusted));
    source.insert(
        "untrusted_linked_prs".into(),
        list(|d| &d.untrusted_pull_requests),
    );
    source.insert("opaque_nodes".into(), list(|d| &d.opaque));
    source.insert("not_planned_parents".into(), list(|d| &d.not_planned));
    Value::Object(source)
}

/// The 1.x result's `frontmatter`: each issue's violation and warning
/// messages, as the core writes them.
fn document_frontmatter(report: &Report) -> Value {
    let by_subject = |list: &[&Finding]| -> BTreeMap<String, Vec<&'static str>> {
        let mut out: BTreeMap<String, Vec<&'static str>> = BTreeMap::new();
        for f in list {
            out.entry(f.subject.to_string())
                .or_default()
                .push(f.message);
        }
        out
    };
    let violations = by_subject(&report.violations);
    json!({
        "violating_issues": violations.len(),
        "violations": violations,
        "warnings": by_subject(&report.warnings),
    })
}

/// The result document `artifact_hash` digests: the 1.x document's shape,
/// with what the renderer emits. It is the Python's document exactly when
/// it holds no intended difference and no gap (docs/topics/output).
fn document(
    plan: &Value,
    report: &Report,
    discovery: Option<&Discovery>,
    compiled: Option<&Compiled>,
) -> Value {
    let source = document_source(plan, discovery);
    let frontmatter = document_frontmatter(report);
    if let Some(c) = compiled {
        let mut doc = c.document(plan, &source, &frontmatter);
        if !report.violations.is_empty() {
            doc["error"] = json!(format!(
                "{} issue(s) have invalid frontmatter",
                doc["frontmatter"]["violating_issues"]
            ));
        }
        return doc;
    }
    if report.cyclic.is_empty() {
        let unknown: Vec<Value> = report
            .unknown
            .iter()
            .filter_map(|f| {
                f.concerns.as_ref().map(|p| {
                    json!({"node": f.subject.to_string(), "unknown_prerequisite": p.to_string()})
                })
            })
            .collect();
        json!({
            "ok": false,
            "error": "Unresolved prerequisites: unknown references and/or stale (merged) hints",
            "unknown_dependencies": unknown,
            "stale_merged_hints": [],
            "soft_or_low_confidence_edges": [],
            "source": source,
            "frontmatter": frontmatter,
        })
    } else {
        json!({
            "ok": false,
            "error": "Cycle detected in hard structural edges",
            "cyclic_nodes": sorted_texts(report.cyclic.iter().map(|f| &f.subject)),
            "unknown_dependencies": [],
            "stale_merged_hints": [],
            "source": source,
            "frontmatter": frontmatter,
        })
    }
}

/// The redundant edges (G5) by source, then target, as text, each with
/// the first child of its source, as text, that reaches its target.
///
/// Reachability is a bit set of descendants per node, built from the last
/// wave back (every child is in a later wave than its parent), and each
/// edge is looked up in the redundant set by key, so a dense graph costs
/// O(N·E/64) to index and O(R·deg) to name.
fn redundant<'a>(
    graph: &'a Graph,
    open: &[&'a IssueRef],
    raw_children: &BTreeMap<&'a IssueRef, Vec<&'a IssueRef>>,
    wave: &BTreeMap<&'a IssueRef, usize>,
) -> Vec<Value> {
    if graph.redundant.is_empty() {
        return Vec::new();
    }
    let index: BTreeMap<&IssueRef, usize> =
        open.iter().enumerate().map(|(i, &id)| (id, i)).collect();
    let words = open.len().div_ceil(64);
    let mut below = vec![vec![0_u64; words]; open.len()];
    let mut by_wave: Vec<&IssueRef> = open.to_vec();
    by_wave.sort_by_key(|id| std::cmp::Reverse(wave.get(id).copied().unwrap_or(0)));
    for u in by_wave {
        let Some(&ui) = index.get(u) else { continue };
        let mut set = vec![0_u64; words];
        for c in raw_children.get(u).into_iter().flatten() {
            if let Some(&ci) = index.get(c) {
                set[ci / 64] |= 1 << (ci % 64);
                for (word, child) in set.iter_mut().zip(&below[ci]) {
                    *word |= child;
                }
            }
        }
        below[ui] = set;
    }
    let reaches = |w: &IssueRef, v: usize| {
        index
            .get(w)
            .is_some_and(|&wi| below[wi][v / 64] >> (v % 64) & 1 == 1)
    };
    let mut out = Vec::new();
    for &u in open {
        let raw = raw_children.get(u).map_or(&[][..], Vec::as_slice);
        for &v in raw {
            let edge = Edge {
                from: u.clone(),
                to: v.clone(),
            };
            let Some(&vi) = index.get(v) else { continue };
            if !graph.redundant.contains(&edge) {
                continue;
            }
            if let Some(w) = raw.iter().find(|&&w| w != v && reaches(w, vi)) {
                out.push(json!({"from": u.to_string(), "to": v.to_string(), "implied_via": w.to_string()}));
            }
        }
    }
    out
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

/// What discovery read that is not a node (rule W1), as 1.x lists it in
/// its result's `source`.
struct Discovery {
    containers: Vec<Value>,
    unmodeled: Vec<Value>,
    untrusted: Vec<Value>,
    untrusted_pull_requests: Vec<Value>,
    opaque: Vec<Value>,
    not_planned: Vec<Value>,
}

impl Discovery {
    /// Each list in the order 1.x writes it: the order discovery read the
    /// issues in (`Graph::visit_order`), and for not-planned prerequisites
    /// that of the task, then of the prerequisite; untrusted pull requests
    /// in the order they were observed.
    fn of<'a>(graph: &'a Graph, shown: &Shown) -> Self {
        let position: BTreeMap<&IssueRef, usize> = graph
            .visit_order
            .iter()
            .enumerate()
            .map(|(i, id)| (id, i))
            .collect();
        let read = |id: &IssueRef| position.get(id).copied().unwrap_or(usize::MAX);
        let in_order = |mut ids: Vec<&'a IssueRef>| -> Vec<&'a IssueRef> {
            ids.sort_by_key(|id| read(id));
            ids
        };
        let containers = in_order(graph.containers.keys().collect())
            .into_iter()
            .map(|id| {
                let mut c = object(json!({"id": id.to_string(), "number": id.number()}));
                shown.title(&mut c, id, false);
                Value::Object(c)
            })
            .collect();
        let unmodeled = in_order(graph.unmodeled.iter().collect())
            .into_iter()
            .map(|id| {
                let mut u = object(json!({"id": id.to_string()}));
                shown.title(&mut u, id, false);
                shown.url(&mut u, id);
                Value::Object(u)
            })
            .collect();
        let untrusted = in_order(graph.untrusted.iter().collect())
            .into_iter()
            .map(|id| json!({"id": id.to_string()}))
            .collect();
        let untrusted_pull_requests = graph
            .untrusted_pull_request_order
            .iter()
            .map(|n| json!({"number": n}))
            .collect();
        let opaque_ids = graph
            .nodes
            .iter()
            .filter(|(_, n)| n.opaque && !n.untrusted)
            .map(|(id, _)| id)
            .collect();
        let opaque = in_order(opaque_ids)
            .into_iter()
            .map(|id| {
                let node = &graph.nodes[id];
                // Every document that names it, containers included, in the
                // order discovery read them, as 1.x lists them.
                let referenced_by = texts(&node.named_by);
                let mut o = object(json!({
                    "id": id.to_string(),
                    "state": if node.complete { "closed" } else { "open" },
                    "referenced_by": referenced_by,
                }));
                shown.title(&mut o, id, false);
                Value::Object(o)
            })
            .collect();
        let mut not_planned_edges: Vec<_> = graph.not_planned.iter().collect();
        not_planned_edges.sort_by_key(|e| (read(&e.to), read(&e.from)));
        let not_planned = not_planned_edges
            .into_iter()
            .map(|e| {
                let mut n =
                    object(json!({"parent": e.from.to_string(), "child": e.to.to_string()}));
                let untrusted = graph.nodes.get(&e.from).is_some_and(|n| n.untrusted);
                shown.title(&mut n, &e.from, untrusted);
                Value::Object(n)
            })
            .collect();
        Self {
            containers,
            unmodeled,
            untrusted,
            untrusted_pull_requests,
            opaque,
            not_planned,
        }
    }
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

fn field(value: &Value, key: &str) -> String {
    value[key].as_str().unwrap_or_default().to_owned()
}

/// Every finding, in the 1.x order of codes.
fn finding_lines(
    report: &Report,
    discovery: Option<&Discovery>,
    compiled: Option<&Compiled>,
) -> Vec<Value> {
    let mut out = Vec::new();
    if let Some(d) = discovery {
        out.extend(discovery_findings(d));
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
        for e in c.redundant() {
            let (u, v, w) = (field(&e, "from"), field(&e, "to"), field(&e, "implied_via"));
            out.push(finding(
                "edge.redundant",
                Some(format!("{u}->{v}")),
                Some(format!("{u} -> {v} is implied via {w}")),
                Some(e),
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
            Some(
                json!({"node": f.subject.to_string(), "unknown_prerequisite": prerequisite.to_string()}),
            ),
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

/// The findings about what discovery read (rule W1).
fn discovery_findings(d: &Discovery) -> Vec<Value> {
    let mut out = Vec::new();
    for c in &d.containers {
        let id = field(c, "id");
        out.push(finding(
            "container.excluded",
            Some(id.clone()),
            Some(format!(
                "{id} is a container: its children are nodes and it is not"
            )),
            Some(c.clone()),
        ));
    }
    for u in &d.unmodeled {
        let id = field(u, "id");
        out.push(finding(
            "issue.unmodeled",
            Some(id.clone()),
            Some(format!(
                "{id} is an open home issue without frontmatter; it is not a node"
            )),
            Some(u.clone()),
        ));
    }
    for u in &d.untrusted {
        out.push(finding(
            "issue.untrusted",
            Some(field(u, "id")),
            None,
            Some(u.clone()),
        ));
    }
    for p in &d.untrusted_pull_requests {
        out.push(finding(
            "pull_request.untrusted",
            None,
            None,
            Some(p.clone()),
        ));
    }
    for o in &d.opaque {
        let id = field(o, "id");
        let by: Vec<&str> = o["referenced_by"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .collect();
        let blocks = if by.is_empty() {
            "nothing".to_owned()
        } else {
            by.join(", ")
        };
        out.push(finding(
            "issue.opaque",
            Some(id.clone()),
            Some(format!(
                "{id} has no frontmatter; it blocks {blocks} until it closes"
            )),
            Some(o.clone()),
        ));
    }
    for n in &d.not_planned {
        let (parent, child) = (field(n, "parent"), field(n, "child"));
        out.push(finding(
            "parent.not_planned",
            Some(parent.clone()),
            Some(format!(
                "{parent} closed as not planned and still satisfies the edge to {child}; review it"
            )),
            Some(n.clone()),
        ));
    }
    out
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::canonical;

    /// Each expected text is what Python writes for the same value:
    /// `json.dumps(v, sort_keys=True, separators=(",", ":")) + "\n"`.
    #[test]
    fn canonical_text_is_what_python_writes() {
        let controls: String = (0_u8..0x20).map(char::from).collect();
        let cases = [
            (
                json!({"k": controls}),
                r#"{"k":"\u0000\u0001\u0002\u0003\u0004\u0005\u0006\u0007\b\t\n\u000b\f\r\u000e\u000f\u0010\u0011\u0012\u0013\u0014\u0015\u0016\u0017\u0018\u0019\u001a\u001b\u001c\u001d\u001e\u001f"}"#,
            ),
            (json!({"k": "\u{7f}"}), r#"{"k":"\u007f"}"#),
            (json!({"k": "\u{e9}"}), r#"{"k":"\u00e9"}"#),
            (json!({"k": "\u{1f600}"}), r#"{"k":"\ud83d\ude00"}"#),
            (json!({"k": "\u{2028}"}), r#"{"k":"\u2028"}"#),
            (json!({"k": "\" \\ / ~"}), r#"{"k":"\" \\ / ~"}"#),
            (
                json!({"b": [1, 0.1786, 0.0, null, true], "a\u{7f}": {"\u{e9}": "x"}}),
                r#"{"a\u007f":{"\u00e9":"x"},"b":[1,0.1786,0.0,null,true]}"#,
            ),
        ];
        for (value, python) in cases {
            assert_eq!(canonical(&value), format!("{python}\n"), "{value}");
        }
    }
}
