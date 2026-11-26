//! A planning run under `issue-dag-planning/2`: discovery and closure
//! (rules D1 to D10), admission (I6), the cross-document rules (X1 to X3),
//! the graph (G1 to G5), status (S1, S2), readiness (Q1, Q2) and the outcome
//! (F1 to F5). Ranking and batch selection (K and B rules) are not here.

use core::fmt;
use std::collections::{BTreeMap, BTreeSet, VecDeque};

use crate::admission::{Admission, Undecided};
use crate::carrier::{Parse, Slot, Value, parse};
use crate::forge::Forge;
use crate::label::Label;
use crate::observation::{Issue, IssueState, Missing, Observed, Parameters, Repo, TRUST_POLICY};
use crate::record::{Kind, MeterClaim, Status};
use crate::reference::IssueRef;
use crate::{Judgement, admit};

/// The label of a finding (profile rule F5).
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Rule {
    /// A document's violation or warning, labelled as format rule V12 states
    /// (X1 included).
    Document(Label),
    /// A reference outside the read scope.
    D3,
    /// A reference to a pull request.
    D4,
    /// A transferred reference.
    D5,
    /// A prerequisite that is a container.
    X2,
    /// An unknown prerequisite.
    X3,
    /// A node of a cycle, or downstream of one.
    G4,
}

impl Rule {
    /// The label as the specification writes it.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Document(label) => label.as_str(),
            Self::D3 => "D3",
            Self::D4 => "D4",
            Self::D5 => "D5",
            Self::X2 => "X2",
            Self::X3 => "X3",
            Self::G4 => "G4",
        }
    }

    /// Whether a finding with this label makes the run invalid. Only a
    /// warning (V10) does not.
    #[must_use]
    pub const fn is_violation(self) -> bool {
        !matches!(self, Self::Document(Label::V10))
    }
}

impl fmt::Display for Rule {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// A finding (profile rule F5): the issue that receives it, its label, and
/// for D3, D5, X2 and X3 the reference it concerns.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Finding {
    /// The issue that receives it.
    pub subject: IssueRef,
    /// The label of the rule.
    pub rule: Rule,
    /// The reference it concerns.
    pub concerns: Option<IssueRef>,
}

/// The status of an open node (rule S2).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum NodeStatus {
    /// `in-review`: a linked pull request is not a draft.
    InReview,
    /// `wip`: every linked pull request is a draft.
    Wip,
    /// `blocked`: opaque, or `.status: blocked`.
    Blocked,
    /// `in-progress`: `.status: active`.
    InProgress,
    /// `parked`: `.status: parked`.
    Parked,
    /// `open`.
    Open,
}

impl NodeStatus {
    /// The status as the profile writes it.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::InReview => "in-review",
            Self::Wip => "wip",
            Self::Blocked => "blocked",
            Self::InProgress => "in-progress",
            Self::Parked => "parked",
            Self::Open => "open",
        }
    }
}

/// A node of the graph (rule G1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Node {
    /// Whether its issue is closed (rule G2).
    pub complete: bool,
    /// Whether it is opaque (rules D6, D7).
    pub opaque: bool,
    /// Whether it is untrusted (rule D6).
    pub untrusted: bool,
    /// Its status (rule S2); `None` for a complete node.
    pub status: Option<NodeStatus>,
    /// Its `.holds` keys; empty for an opaque node (rule T2).
    pub holds: BTreeSet<String>,
    /// Its `.meters` claims; empty for an opaque node.
    pub meters: Vec<MeterClaim>,
}

/// An edge `(from, to)`: `from` must be complete before `to` is correct.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Edge {
    /// The prerequisite.
    pub from: IssueRef,
    /// The dependent.
    pub to: IssueRef,
}

/// The graph of a run, its readiness and the lists rule W1 reports.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Graph {
    /// The nodes (rule G1).
    pub nodes: BTreeMap<IssueRef, Node>,
    /// The containers, with their children in written order (rules D9, W1).
    pub containers: BTreeMap<IssueRef, Vec<IssueRef>>,
    /// The unmodeled issues (rule D7).
    pub unmodeled: BTreeSet<IssueRef>,
    /// Every issue that is not admitted (rules D6, W1).
    pub untrusted: BTreeSet<IssueRef>,
    /// The numbers of the pull requests that close an issue and are not
    /// admitted (rules AD9, W1).
    pub untrusted_pull_requests: BTreeSet<u64>,
    /// The edges of the graph (rule G3), redundant ones included.
    pub edges: BTreeSet<Edge>,
    /// The satisfied edges: each completed prerequisite of an open task.
    pub satisfied: BTreeSet<Edge>,
    /// The satisfied edges whose prerequisite was closed as `not_planned`.
    pub not_planned: BTreeSet<Edge>,
    /// The edges the reduction removes (rule G5).
    pub redundant: BTreeSet<Edge>,
    /// The ready set (rule Q1), unordered: its rank order is rule K6's.
    pub ready: BTreeSet<IssueRef>,
}

impl Graph {
    /// The dispatchable subset of the ready set (rule Q2).
    #[must_use]
    pub fn dispatchable(&self) -> BTreeSet<IssueRef> {
        self.ready
            .iter()
            .filter(|id| {
                self.nodes.get(*id).is_some_and(|n| {
                    !n.opaque && !n.untrusted && n.status != Some(NodeStatus::Blocked)
                })
            })
            .cloned()
            .collect()
    }
}

/// Why a run is rejected (profile rule I2).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Rejection {
    /// The trust policy is not `taskalisk/threat-model`.
    UnknownPolicy(String),
    /// A root is not a reference under format rule L1.
    RootNotAReference(String),
    /// A root is in a repository outside the read scope.
    RootOutsideScope(IssueRef),
}

/// The outcome of a run (profile rule F1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Outcome {
    /// A run parameter is invalid.
    Rejected(Rejection),
    /// A required observation is unavailable; no graph (rule F2).
    Incomplete {
        /// Why the observation was unavailable, as recorded.
        unavailable: String,
    },
    /// Some rule fails. The graph is reported for diagnosis (rule F3) unless
    /// the edges could not all be resolved (X3) or form a cycle (G4).
    Invalid {
        /// The findings, warnings included.
        findings: BTreeSet<Finding>,
        /// The graph, for diagnosis only.
        graph: Option<Graph>,
    },
    /// A plan.
    Planned {
        /// The findings: warnings only.
        findings: BTreeSet<Finding>,
        /// The graph.
        graph: Graph,
    },
}

/// Plans over the observations a forge answers with.
///
/// # Errors
///
/// [`Missing`] when the run reads an observation that was not recorded
/// (bundle rule OB5): the evidence is unusable and no outcome is given.
pub fn plan<F: Forge + ?Sized>(parameters: &Parameters, forge: &F) -> Result<Outcome, Missing> {
    if parameters.trust.policy != TRUST_POLICY {
        return Ok(Outcome::Rejected(Rejection::UnknownPolicy(
            parameters.trust.policy.clone(),
        )));
    }
    let mut roots = Vec::new();
    for text in &parameters.roots {
        let Some(root) = IssueRef::parse(text) else {
            return Ok(Outcome::Rejected(Rejection::RootNotAReference(
                text.clone(),
            )));
        };
        if !parameters.read_scope.contains(&Repo::of(&root)) {
            return Ok(Outcome::Rejected(Rejection::RootOutsideScope(root)));
        }
        roots.push(root);
    }
    match Run::new(parameters, forge).execute(roots) {
        Ok(outcome) => Ok(outcome),
        Err(Undecided::Unavailable(unavailable)) => Ok(Outcome::Incomplete { unavailable }),
        Err(Undecided::Missing(missing)) => Err(missing),
    }
}

fn value<T>(slot: Observed<T>) -> Result<T, Undecided> {
    match slot {
        Observed::Value(v) => Ok(v),
        Observed::Unavailable(why) => Err(Undecided::Unavailable(why)),
    }
}

/// What the fields of a document say, read whether or not it is valid
/// (rule D8): an invalid document is still walked, and is still a node.
#[derive(Clone, Debug, Default)]
struct Reading {
    kind: Option<Kind>,
    /// `.blocked_by` of a task: its references, without the issue's own
    /// address, in written order.
    blocked_by: Vec<IssueRef>,
    /// `.children` of a container, likewise.
    children: Vec<IssueRef>,
    status: Option<Status>,
    holds: BTreeSet<String>,
    meters: Vec<MeterClaim>,
}

impl Reading {
    fn of(body: &str, address: &IssueRef) -> Self {
        let Parse::Block(block) = parse(body) else {
            return Self::default();
        };
        let one = |key: &str| match block.slot(key) {
            Slot::One(value) => Some(value),
            Slot::Repeated | Slot::Absent => None,
        };
        let refs = |key: &str| match one(key) {
            Some(Value::List(items)) => items
                .iter()
                .filter_map(|i| IssueRef::parse(i))
                .filter(|r| r != address)
                .collect(),
            _ => Vec::new(),
        };
        let kind = match one(".kind") {
            Some(Value::String(text)) => Kind::parse(text),
            _ => None,
        };
        let status = match one(".status") {
            Some(Value::String(text)) => Status::parse(text),
            _ => None,
        };
        let holds = match one(".holds") {
            Some(Value::List(items)) => items.iter().filter(|i| !i.is_empty()).cloned().collect(),
            _ => BTreeSet::new(),
        };
        let meters = match one(".meters") {
            Some(Value::List(items)) => items.iter().filter_map(|i| MeterClaim::parse(i)).collect(),
            _ => Vec::new(),
        };
        Self {
            kind,
            blocked_by: if kind == Some(Kind::Task) {
                refs(".blocked_by")
            } else {
                Vec::new()
            },
            children: if kind == Some(Kind::Container) {
                refs(".children")
            } else {
                Vec::new()
            },
            status,
            holds,
            meters,
        }
    }

    /// The references rule D8 adds to the closure.
    fn names(&self) -> impl Iterator<Item = &IssueRef> {
        self.blocked_by.iter().chain(self.children.iter())
    }
}

/// What a visited reference turned out to be.
enum Visit {
    /// Outside the read scope; never read (D3).
    OutOfScope,
    /// A pull request (D4).
    PullRequest,
    /// Transferred (D5).
    Transferred,
    /// Not admitted (D6).
    Untrusted(Box<Issue>),
    /// Admitted, with no frontmatter block (D7).
    NoDocument(Box<Issue>),
    /// Admitted, with a document (D8).
    Document(Box<Document>),
}

/// An admitted issue that holds a document.
struct Document {
    issue: Issue,
    judgement: Judgement,
    reading: Reading,
}

/// The closure of a run (D2): every reference visited, and the documents
/// that name each one.
struct Closure {
    has_roots: bool,
    seeds: BTreeSet<IssueRef>,
    visits: BTreeMap<IssueRef, Visit>,
    named_by: BTreeMap<IssueRef, BTreeSet<IssueRef>>,
}

impl Closure {
    /// A seed that no document read in the run names (D6, D7).
    fn unnamed_seed(&self, reference: &IssueRef) -> bool {
        self.seeds.contains(reference)
            && self.named_by.get(reference).is_none_or(BTreeSet::is_empty)
    }

    /// F5: the issues that receive the D3 or D5 finding about a reference:
    /// each document that names it, or the reference itself when nobody
    /// does.
    fn namers(&self, reference: &IssueRef) -> Vec<IssueRef> {
        self.named_by.get(reference).map_or_else(
            || vec![reference.clone()],
            |by| by.iter().cloned().collect(),
        )
    }
}

struct Run<'a, F: Forge + ?Sized> {
    parameters: &'a Parameters,
    forge: &'a F,
    admission: Admission<'a, F>,
}

impl<'a, F: Forge + ?Sized> Run<'a, F> {
    fn new(parameters: &'a Parameters, forge: &'a F) -> Self {
        Self {
            parameters,
            forge,
            admission: Admission::new(
                forge,
                &parameters.read_scope,
                &parameters.trust.logins,
                parameters.trust.codeowners,
            ),
        }
    }

    fn execute(mut self, roots: Vec<IssueRef>) -> Result<Outcome, Undecided> {
        let has_roots = !roots.is_empty();
        // D1: the seeds.
        let seeds = if has_roots {
            roots
        } else {
            value(self.forge.home_open_issues()?)?
        };
        let (linked, untrusted_pull_requests) = self.pull_requests()?;
        let closure = self.closure(seeds, has_roots)?;
        let mut assembly = Assembly::new(&closure, untrusted_pull_requests);
        assembly.prerequisites();
        assembly.statuses(&linked, &self.parameters.home);
        Ok(assembly.outcome())
    }

    /// I4 and AD9: for each issue, the draft flags of the admitted pull
    /// requests that close it; and the numbers of those not admitted.
    #[allow(clippy::type_complexity)]
    fn pull_requests(
        &mut self,
    ) -> Result<(BTreeMap<IssueRef, Vec<bool>>, BTreeSet<u64>), Undecided> {
        let mut linked: BTreeMap<IssueRef, Vec<bool>> = BTreeMap::new();
        let mut untrusted = BTreeSet::new();
        let home = &self.parameters.home;
        for pull in value(self.forge.home_open_pull_requests()?)? {
            if pull.closes.is_empty() {
                continue;
            }
            if self.admission.pull_request_admitted(&pull, home)? {
                let draft = value(pull.draft.clone())?;
                for closed in pull.closes {
                    linked.entry(closed).or_default().push(draft);
                }
            } else {
                untrusted.insert(pull.number);
            }
        }
        Ok((linked, untrusted))
    }

    /// D2: visits the seeds and every reference D8 adds, each once.
    fn closure(&mut self, seeds: Vec<IssueRef>, has_roots: bool) -> Result<Closure, Undecided> {
        let mut closure = Closure {
            has_roots,
            seeds: seeds.iter().cloned().collect(),
            visits: BTreeMap::new(),
            named_by: BTreeMap::new(),
        };
        let mut queue: VecDeque<IssueRef> = seeds.into_iter().collect();
        while let Some(reference) = queue.pop_front() {
            if closure.visits.contains_key(&reference) {
                continue;
            }
            let visit = self.visit(&reference)?;
            if let Visit::Document(document) = &visit {
                for name in document.reading.names() {
                    closure
                        .named_by
                        .entry(name.clone())
                        .or_default()
                        .insert(reference.clone());
                    queue.push_back(name.clone());
                }
            }
            closure.visits.insert(reference, visit);
        }
        Ok(closure)
    }

    /// D3 to D8 for one reference.
    fn visit(&mut self, reference: &IssueRef) -> Result<Visit, Undecided> {
        let repo = Repo::of(reference);
        if !self.parameters.read_scope.contains(&repo) {
            return Ok(Visit::OutOfScope);
        }
        let issue = value(self.forge.issue(reference)?)?;
        if issue.pull_request {
            return Ok(Visit::PullRequest);
        }
        if issue.address != *reference {
            return Ok(Visit::Transferred);
        }
        let author = issue.author.as_ref();
        if !self
            .admission
            .trusted(author, &repo, issue.author_association.as_deref())?
        {
            return Ok(Visit::Untrusted(Box::new(issue)));
        }
        let body = value(issue.body.clone())?;
        if !self.admission.editors_trusted(author, &body, &repo)? {
            return Ok(Visit::Untrusted(Box::new(issue)));
        }
        let judgement = admit(&body.text, Some(&issue.address));
        if judgement == Judgement::NoDocument {
            return Ok(Visit::NoDocument(Box::new(issue)));
        }
        let reading = Reading::of(&body.text, &issue.address);
        Ok(Visit::Document(Box::new(Document {
            issue,
            judgement,
            reading,
        })))
    }
}

/// The graph as it is assembled from a closure, with the findings so far
/// and what each node was read from.
struct Assembly<'c> {
    graph: Graph,
    findings: BTreeSet<Finding>,
    readings: BTreeMap<IssueRef, &'c Reading>,
    issues: BTreeMap<IssueRef, &'c Issue>,
}

impl<'c> Assembly<'c> {
    /// D3 to D9 and G1: the nodes, containers and lists, and the findings
    /// of discovery and of each document.
    fn new(closure: &'c Closure, untrusted_pull_requests: BTreeSet<u64>) -> Self {
        let mut a = Self {
            graph: Graph {
                untrusted_pull_requests,
                ..Graph::default()
            },
            findings: BTreeSet::new(),
            readings: BTreeMap::new(),
            issues: BTreeMap::new(),
        };
        for (reference, visit) in &closure.visits {
            match visit {
                Visit::OutOfScope => a.about(closure, reference, Rule::D3),
                Visit::Transferred => a.about(closure, reference, Rule::D5),
                Visit::PullRequest => a.finding(reference, Rule::D4, None),
                Visit::Untrusted(issue) => {
                    a.graph.untrusted.insert(reference.clone());
                    if !closure.unnamed_seed(reference) {
                        a.opaque(reference, issue, true);
                    }
                }
                Visit::NoDocument(issue) => {
                    if !closure.has_roots && closure.unnamed_seed(reference) {
                        a.graph.unmodeled.insert(reference.clone());
                    } else {
                        a.opaque(reference, issue, false);
                    }
                }
                Visit::Document(document) => a.document(reference, document),
            }
        }
        a
    }

    fn finding(&mut self, subject: &IssueRef, rule: Rule, concerns: Option<&IssueRef>) {
        self.findings.insert(Finding {
            subject: subject.clone(),
            rule,
            concerns: concerns.cloned(),
        });
    }

    /// A D3 or D5 finding about `reference`, to each issue F5 names.
    fn about(&mut self, closure: &Closure, reference: &IssueRef, rule: Rule) {
        for subject in closure.namers(reference) {
            self.finding(&subject, rule, Some(reference));
        }
    }

    fn opaque(&mut self, reference: &IssueRef, issue: &'c Issue, untrusted: bool) {
        self.graph.nodes.insert(
            reference.clone(),
            Node {
                complete: issue.state == IssueState::Closed,
                opaque: true,
                untrusted,
                status: None,
                holds: BTreeSet::new(),
                meters: Vec::new(),
            },
        );
        self.issues.insert(reference.clone(), issue);
    }

    fn document(&mut self, reference: &IssueRef, document: &'c Document) {
        let labels: Vec<Label> = match &document.judgement {
            Judgement::NoDocument => Vec::new(),
            Judgement::Valid { warnings, .. } => warnings.iter().copied().collect(),
            Judgement::Invalid(v) => v.violations.iter().copied().collect(),
        };
        for label in labels {
            self.finding(reference, Rule::Document(label), None);
        }
        let reading = &document.reading;
        if reading.kind == Some(Kind::Container) {
            self.graph
                .containers
                .insert(reference.clone(), reading.children.clone());
            return;
        }
        self.graph.nodes.insert(
            reference.clone(),
            Node {
                complete: document.issue.state == IssueState::Closed,
                opaque: false,
                untrusted: false,
                status: None,
                holds: reading.holds.clone(),
                meters: reading.meters.clone(),
            },
        );
        self.readings.insert(reference.clone(), reading);
        self.issues.insert(reference.clone(), &document.issue);
    }

    /// X2, X3 and G3, for each open task.
    fn prerequisites(&mut self) {
        let tasks: Vec<(IssueRef, &Reading)> = self
            .readings
            .iter()
            .filter(|(id, _)| self.graph.nodes.get(*id).is_some_and(|n| !n.complete))
            .map(|(id, r)| (id.clone(), *r))
            .collect();
        for (task, reading) in tasks {
            let mut distinct = BTreeSet::new();
            for prerequisite in &reading.blocked_by {
                if distinct.insert(prerequisite) {
                    self.prerequisite(prerequisite, &task);
                }
            }
        }
    }

    fn prerequisite(&mut self, prerequisite: &IssueRef, task: &IssueRef) {
        if self.graph.containers.contains_key(prerequisite) {
            self.finding(task, Rule::X2, Some(prerequisite));
            return;
        }
        let Some(node) = self.graph.nodes.get(prerequisite) else {
            self.finding(task, Rule::X3, Some(prerequisite));
            return;
        };
        let edge = Edge {
            from: prerequisite.clone(),
            to: task.clone(),
        };
        if !node.complete {
            self.graph.edges.insert(edge);
            return;
        }
        let not_planned = self
            .issues
            .get(prerequisite)
            .is_some_and(|i| i.state_reason.as_deref() == Some("not_planned"));
        if not_planned {
            self.graph.not_planned.insert(edge.clone());
        }
        self.graph.satisfied.insert(edge);
    }

    /// S1 and S2: the status of each open node, from the draft flags of the
    /// admitted pull requests that close each issue.
    fn statuses(&mut self, linked: &BTreeMap<IssueRef, Vec<bool>>, home: &Repo) {
        for (id, node) in &mut self.graph.nodes {
            if node.complete {
                continue;
            }
            let drafts: &[bool] = if Repo::of(id) == *home && !node.untrusted {
                linked.get(id).map_or(&[], Vec::as_slice)
            } else {
                &[]
            };
            node.status = Some(if drafts.iter().any(|draft| !draft) {
                NodeStatus::InReview
            } else if !drafts.is_empty() {
                NodeStatus::Wip
            } else if node.opaque {
                NodeStatus::Blocked
            } else {
                match self.readings.get(id).and_then(|r| r.status) {
                    Some(Status::Active) => NodeStatus::InProgress,
                    Some(Status::Parked) => NodeStatus::Parked,
                    Some(Status::Blocked) => NodeStatus::Blocked,
                    None => NodeStatus::Open,
                }
            });
        }
    }

    /// G4, G5, Q1 and F1.
    fn outcome(mut self) -> Outcome {
        for node in cyclic(&self.graph) {
            self.finding(&node, Rule::G4, None);
        }
        let unresolved = self
            .findings
            .iter()
            .any(|f| matches!(f.rule, Rule::X3 | Rule::G4));
        let mut graph = self.graph;
        graph.redundant = redundant(&graph.edges);
        graph.ready = graph
            .nodes
            .iter()
            .filter(|(id, n)| !n.complete && !graph.edges.iter().any(|e| e.to == **id))
            .map(|(id, _)| id.clone())
            .collect();
        let findings = self.findings;
        if findings.iter().any(|f| f.rule.is_violation()) {
            Outcome::Invalid {
                findings,
                graph: (!unresolved).then_some(graph),
            }
        } else {
            Outcome::Planned { findings, graph }
        }
    }
}

/// G4: the open nodes left after repeatedly removing every open node with no
/// incoming edge.
fn cyclic(graph: &Graph) -> BTreeSet<IssueRef> {
    let mut left: BTreeSet<&IssueRef> = graph
        .nodes
        .iter()
        .filter(|(_, n)| !n.complete)
        .map(|(id, _)| id)
        .collect();
    loop {
        let sources: Vec<&IssueRef> = left
            .iter()
            .copied()
            .filter(|id| {
                !graph
                    .edges
                    .iter()
                    .any(|e| e.to == **id && left.contains(&e.from))
            })
            .collect();
        if sources.is_empty() {
            return left.into_iter().cloned().collect();
        }
        for id in sources {
            left.remove(id);
        }
    }
}

/// G5: the edges `(u, v)` for which another path leads from `u` to `v`.
fn redundant(edges: &BTreeSet<Edge>) -> BTreeSet<Edge> {
    let mut children: BTreeMap<&IssueRef, Vec<&IssueRef>> = BTreeMap::new();
    for e in edges {
        children.entry(&e.from).or_default().push(&e.to);
    }
    let reaches = |start: &IssueRef, target: &IssueRef| {
        let mut stack = vec![start];
        let mut seen = BTreeSet::new();
        while let Some(u) = stack.pop() {
            if u == target {
                return true;
            }
            if seen.insert(u) {
                stack.extend(children.get(u).into_iter().flatten().copied());
            }
        }
        false
    };
    edges
        .iter()
        .filter(|e| {
            children
                .get(&e.from)
                .into_iter()
                .flatten()
                .any(|w| *w != &e.to && reaches(w, &e.to))
        })
        .cloned()
        .collect()
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, BTreeSet};

    use super::{NodeStatus, Outcome, plan};
    use crate::forge::{Observations, RecordedForge};
    use crate::observation::{
        Actor, Body, Issue, IssueState, Observed, Parameters, ReadScope, Repo, TRUST_POLICY,
        TrustParameters,
    };
    use crate::reference::IssueRef;

    fn reference(text: &str) -> IssueRef {
        IssueRef::parse(text).expect("a reference")
    }

    fn parameters(roots: &[&str]) -> Parameters {
        Parameters {
            home: Repo::parse("o/r").expect("a repository"),
            roots: roots.iter().map(|r| (*r).to_owned()).collect(),
            read_scope: ReadScope {
                owners: BTreeSet::from(["o".to_owned()]),
                repositories: BTreeSet::new(),
            },
            trust: TrustParameters {
                policy: TRUST_POLICY.to_owned(),
                logins: Vec::new(),
                codeowners: false,
            },
            capacities: BTreeMap::new(),
        }
    }

    fn owned_issue(address: &str, text: &str) -> Observed<Issue> {
        let owner = Actor {
            login: "o".to_owned(),
            actor_type: "User".to_owned(),
        };
        Observed::Value(Issue {
            address: reference(address),
            pull_request: false,
            state: IssueState::Open,
            state_reason: None,
            author: Some(owner.clone()),
            author_association: Some("OWNER".to_owned()),
            body: Observed::Value(Body {
                text: text.to_owned(),
                editors: vec![Some(owner)],
            }),
        })
    }

    #[test]
    fn d7_a_root_without_frontmatter_is_an_opaque_node() {
        let observations = Observations {
            home_open_pull_requests: Some(Observed::Value(Vec::new())),
            issues: BTreeMap::from([(reference("o/r#1"), owned_issue("o/r#1", "Plain body."))]),
            ..Observations::default()
        };
        let outcome = plan(&parameters(&["o/r#1"]), &RecordedForge::new(&observations));
        let Ok(Outcome::Planned { graph, .. }) = outcome else {
            panic!("expected a plan, got {outcome:?}");
        };
        assert!(graph.unmodeled.is_empty());
        let node = &graph.nodes[&reference("o/r#1")];
        assert!(node.opaque);
        assert_eq!(node.status, Some(NodeStatus::Blocked));
        assert!(graph.dispatchable().is_empty());
    }

    #[test]
    fn ob5_a_slot_that_was_not_recorded_gives_no_outcome() {
        let observations = Observations {
            home_open_pull_requests: Some(Observed::Value(Vec::new())),
            ..Observations::default()
        };
        let outcome = plan(&parameters(&["o/r#1"]), &RecordedForge::new(&observations));
        assert!(outcome.is_err(), "got {outcome:?}");
    }
}
