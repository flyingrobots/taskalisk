//! A planning run under `issue-dag-planning/2`: discovery and closure
//! (rules D1 to D10), admission (I6), the cross-document rules (X1 to X3),
//! the graph (G1 to G5), status (S1, S2), readiness (Q1, Q2) and the outcome
//! (F1 to F5). Ranking and batch selection (K and B rules) are in `rank` and
//! `batch`.

use std::collections::{BTreeMap, BTreeSet, VecDeque};

use crate::admission::{Admission, Gaps, Undecided, lookup};
use crate::carrier::{Parse, Slot, Value, parse};
use crate::finding::{Finding, Rule, Severity};
use crate::forge::Forge;
use crate::label::Label;
use crate::observation::{Issue, IssueState, Missing, Observed, Parameters, Repo, TRUST_POLICY};
use crate::record::{Kind, MeterClaim, Status};
use crate::reference::IssueRef;
use crate::{Judgement, judge};

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
    fn of(parsed: &Parse, address: &IssueRef) -> Self {
        let Parse::Block(block) = parsed else {
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

/// For each issue, the draft slots of the admitted pull requests that close
/// it (S1). A slot is read only where S2 needs it (I5).
type Linked = BTreeMap<IssueRef, Vec<Observed<bool>>>;

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
    /// each document that names it, or the reference itself when it is a
    /// root that no document names. A seed of the home listing is not a
    /// root: unnamed, it gives no finding (D5).
    fn namers(&self, reference: &IssueRef) -> Vec<IssueRef> {
        match self.named_by.get(reference) {
            Some(by) => by.iter().cloned().collect(),
            None if self.has_roots && self.seeds.contains(reference) => vec![reference.clone()],
            None => Vec::new(),
        }
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

    /// Discovery reads every observation the rules reach before it decides
    /// that the run cannot go on: one lookup that cannot be made does not
    /// stop the others (D1, D2, I4), so neither the order of the roots nor
    /// that of discovery changes the result, and a missing slot is never
    /// hidden by an unavailable one (OB5).
    fn execute(mut self, roots: Vec<IssueRef>) -> Result<Outcome, Undecided> {
        let has_roots = !roots.is_empty();
        let mut gaps = Gaps::default();
        // D1: the seeds.
        let seeds = if has_roots {
            roots
        } else {
            gaps.note(lookup(self.forge.home_open_issues()))
                .unwrap_or_default()
        };
        let (linked, untrusted_pull_requests) = self.pull_requests(&mut gaps);
        let closure = self.closure(seeds, has_roots, &mut gaps);
        gaps.check()?;
        let mut assembly = Assembly::new(&closure, untrusted_pull_requests);
        assembly.prerequisites();
        assembly.statuses(&linked, &self.parameters.home)?;
        Ok(assembly.outcome())
    }

    /// I4 and AD9: for each issue, the draft slots of the admitted pull
    /// requests that close it; and the numbers of those not admitted.
    fn pull_requests(&mut self, gaps: &mut Gaps) -> (Linked, BTreeSet<u64>) {
        let mut linked = Linked::new();
        let mut untrusted = BTreeSet::new();
        let home = &self.parameters.home;
        let pulls = gaps
            .note(lookup(self.forge.home_open_pull_requests()))
            .unwrap_or_default();
        for pull in pulls {
            if pull.closes.is_empty() {
                continue;
            }
            match gaps.note(self.admission.pull_request_admitted(&pull, home)) {
                Some(true) => {
                    for closed in pull.closes {
                        linked.entry(closed).or_default().push(pull.draft.clone());
                    }
                }
                Some(false) => {
                    untrusted.insert(pull.number);
                }
                None => {}
            }
        }
        (linked, untrusted)
    }

    /// D2: visits the seeds and every reference D8 adds, each once. A
    /// reference whose visit cannot be decided is noted in `gaps` and adds
    /// nothing; discovery goes on with the rest.
    fn closure(&mut self, seeds: Vec<IssueRef>, has_roots: bool, gaps: &mut Gaps) -> Closure {
        let mut closure = Closure {
            has_roots,
            seeds: seeds.iter().cloned().collect(),
            visits: BTreeMap::new(),
            named_by: BTreeMap::new(),
        };
        let mut undecided = BTreeSet::new();
        let mut queue: VecDeque<IssueRef> = seeds.into_iter().collect();
        while let Some(reference) = queue.pop_front() {
            if closure.visits.contains_key(&reference) || undecided.contains(&reference) {
                continue;
            }
            let Some(visit) = gaps.note(self.visit(&reference)) else {
                undecided.insert(reference);
                continue;
            };
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
        closure
    }

    /// D3 to D8 for one reference.
    fn visit(&mut self, reference: &IssueRef) -> Result<Visit, Undecided> {
        let repo = Repo::of(reference);
        if !self.parameters.read_scope.contains(&repo) {
            return Ok(Visit::OutOfScope);
        }
        let issue = lookup(self.forge.issue(reference))?;
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
        // One parse serves both the judgement and the reading.
        let parsed = parse(&body.text);
        let judgement = judge(&parsed, Some(&issue.address));
        if judgement == Judgement::NoDocument {
            return Ok(Visit::NoDocument(Box::new(issue)));
        }
        let reading = Reading::of(&parsed, &issue.address);
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
        self.findings
            .insert(Finding::new(subject.clone(), rule, concerns.cloned()));
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
    /// admitted pull requests that close it. Those flags are read here, and
    /// only here: an unavailable one makes the run incomplete (I5).
    fn statuses(&mut self, linked: &Linked, home: &Repo) -> Result<(), Undecided> {
        for (id, node) in &mut self.graph.nodes {
            if node.complete {
                continue;
            }
            let drafts: Vec<bool> = if Repo::of(id) == *home && !node.untrusted {
                linked
                    .get(id)
                    .into_iter()
                    .flatten()
                    .map(|slot| value(slot.clone()))
                    .collect::<Result<_, _>>()?
            } else {
                Vec::new()
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
        Ok(())
    }

    /// G4, G5, Q1 and F1.
    fn outcome(mut self) -> Outcome {
        let indexed = Indexed::of(&self.graph);
        let (order, cyclic) = indexed.kahn();
        for node in &cyclic {
            self.finding(node, Rule::G4, None);
        }
        let unresolved = self
            .findings
            .iter()
            .any(|f| f.code == Rule::X3.code() || f.code == Rule::G4.code());
        let redundant = if cyclic.is_empty() {
            indexed.redundant(&order)
        } else {
            BTreeSet::new()
        };
        let mut graph = self.graph;
        graph.redundant = redundant;
        let targets: BTreeSet<&IssueRef> = graph.edges.iter().map(|e| &e.to).collect();
        graph.ready = graph
            .nodes
            .iter()
            .filter(|(id, n)| !n.complete && !targets.contains(id))
            .map(|(id, _)| id.clone())
            .collect();
        let findings = self.findings;
        if findings.iter().any(|f| f.severity == Severity::Error) {
            Outcome::Invalid {
                findings,
                graph: (!unresolved).then_some(graph),
            }
        } else {
            Outcome::Planned { findings, graph }
        }
    }
}

/// The open nodes and the edges between them, by position, for Kahn's
/// algorithm (G4) and the reduction (G5).
pub struct Indexed {
    pub ids: Vec<IssueRef>,
    pub children: Vec<Vec<usize>>,
    in_degree: Vec<usize>,
}

impl Indexed {
    pub fn of(graph: &Graph) -> Self {
        let ids: Vec<IssueRef> = graph
            .nodes
            .iter()
            .filter(|(_, n)| !n.complete)
            .map(|(id, _)| id.clone())
            .collect();
        let position: BTreeMap<&IssueRef, usize> =
            ids.iter().enumerate().map(|(i, id)| (id, i)).collect();
        let mut children = vec![Vec::new(); ids.len()];
        let mut in_degree = vec![0; ids.len()];
        for edge in &graph.edges {
            // Every edge joins two open nodes (G3); `edges` holds each once.
            if let (Some(&from), Some(&to)) = (position.get(&edge.from), position.get(&edge.to)) {
                children[from].push(to);
                in_degree[to] += 1;
            }
        }
        Self {
            ids,
            children,
            in_degree,
        }
    }

    /// Kahn's algorithm: the open nodes in a topological order, and (G4)
    /// those left after repeatedly removing every node with no incoming
    /// edge: the members of every cycle and every node downstream of one.
    pub fn kahn(&self) -> (Vec<usize>, BTreeSet<IssueRef>) {
        let mut in_degree = self.in_degree.clone();
        let mut sources: Vec<usize> = (0..self.ids.len()).filter(|&i| in_degree[i] == 0).collect();
        let mut order = Vec::with_capacity(self.ids.len());
        while let Some(u) = sources.pop() {
            order.push(u);
            for &v in &self.children[u] {
                in_degree[v] -= 1;
                if in_degree[v] == 0 {
                    sources.push(v);
                }
            }
        }
        let left = (0..self.ids.len())
            .filter(|&i| in_degree[i] > 0)
            .map(|i| self.ids[i].clone())
            .collect();
        (order, left)
    }

    /// G5, for an acyclic graph with this topological order: `(u, v)` is
    /// redundant when `v` descends from another child of `u`. Descendant
    /// sets are bit sets built in reverse topological order.
    fn redundant(&self, order: &[usize]) -> BTreeSet<Edge> {
        // An edge `(u, v)` is redundant only through another child of `u`.
        // With no node of two children there is none, and the descendant
        // sets, n² bits, are not worth building.
        if self.children.iter().all(|children| children.len() < 2) {
            return BTreeSet::new();
        }
        let words = self.ids.len().div_ceil(64);
        let mut descendants = vec![vec![0_u64; words]; self.ids.len()];
        for &u in order.iter().rev() {
            let mut set = vec![0_u64; words];
            for &c in &self.children[u] {
                set[c / 64] |= 1 << (c % 64);
                for (word, child_word) in set.iter_mut().zip(&descendants[c]) {
                    *word |= child_word;
                }
            }
            descendants[u] = set;
        }
        let mut redundant = BTreeSet::new();
        for (u, children) in self.children.iter().enumerate() {
            // What the children of `u` reach; a child is never its own
            // descendant in an acyclic graph.
            let mut below = vec![0_u64; words];
            for &c in children {
                for (word, child_word) in below.iter_mut().zip(&descendants[c]) {
                    *word |= child_word;
                }
            }
            for &v in children {
                if below[v / 64] & (1 << (v % 64)) != 0 {
                    redundant.insert(Edge {
                        from: self.ids[u].clone(),
                        to: self.ids[v].clone(),
                    });
                }
            }
        }
        redundant
    }
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, BTreeSet};

    use std::time::{Duration, Instant};

    use super::{Edge, NodeStatus, Outcome, plan};
    use crate::forge::{Observations, RecordedForge};
    use crate::observation::{
        Actor, Body, Issue, IssueState, Missing, Observed, Parameters, PullRequest, ReadScope,
        Repo, TRUST_POLICY, TrustParameters,
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

    /// The body of an open task `o/r#n` with these prerequisites.
    fn task(n: u32, blocked_by: &[u32]) -> String {
        let items: Vec<String> = blocked_by.iter().map(|b| format!("o/r#{b}")).collect();
        format!(
            "```yaml\n.dag: issue-dag/2\n.id: o/r#{n}\n.kind: task\n.type: feature\n.blocked_by: [{}]\n```\n",
            items.join(", ")
        )
    }

    fn tasks(bodies: Vec<(u32, String)>) -> Observations {
        Observations {
            home_open_pull_requests: Some(Observed::Value(Vec::new())),
            issues: bodies
                .into_iter()
                .map(|(n, body)| {
                    let address = format!("o/r#{n}");
                    (reference(&address), owned_issue(&address, &body))
                })
                .collect(),
            ..Observations::default()
        }
    }

    /// The bound the large graphs below must plan within. Wall-clock time
    /// depends on the machine's load, so the default suite checks only the
    /// graphs; the `perf_` tests, ignored by default, check the bound, and
    /// CI runs them in a release build as a job of their own.
    const LARGE_GRAPH_BOUND: Duration = Duration::from_secs(1);
    const LARGE: u32 = 5_000;

    #[test]
    fn a_chain_of_5000_tasks_plans() {
        chain_of_5000();
    }

    #[test]
    #[ignore = "wall-clock bound; run with --release --ignored"]
    fn perf_a_chain_of_5000_tasks_plans_within_the_bound() {
        let took = chain_of_5000();
        assert!(took < LARGE_GRAPH_BOUND, "a chain took {took:?}");
    }

    #[test]
    fn a_wide_graph_of_5000_tasks_plans() {
        wide_graph_of_5000();
    }

    #[test]
    #[ignore = "wall-clock bound; run with --release --ignored"]
    fn perf_a_wide_graph_of_5000_tasks_plans_within_the_bound() {
        let took = wide_graph_of_5000();
        assert!(took < LARGE_GRAPH_BOUND, "a wide graph took {took:?}");
    }

    #[test]
    fn g4_a_long_cycle_and_what_is_downstream_of_it_are_reported() {
        long_cycle();
    }

    #[test]
    #[ignore = "wall-clock bound; run with --release --ignored"]
    fn perf_g4_a_long_cycle_is_reported_within_the_bound() {
        let took = long_cycle();
        assert!(took < LARGE_GRAPH_BOUND, "a cycle took {took:?}");
    }

    /// Plans a chain of [`LARGE`] tasks, checks the graph, and returns how
    /// long the plan took.
    fn chain_of_5000() -> Duration {
        let observations = tasks(
            (1..=LARGE)
                .map(|n| {
                    let before: Vec<u32> = (n > 1).then(|| n - 1).into_iter().collect();
                    (n, task(n, &before))
                })
                .collect(),
        );
        let root = format!("o/r#{LARGE}");
        let start = Instant::now();
        let outcome = plan(&parameters(&[&root]), &RecordedForge::new(&observations));
        let took = start.elapsed();
        let Ok(Outcome::Planned { graph, .. }) = outcome else {
            panic!("expected a plan, got {outcome:?}");
        };
        assert_eq!(graph.nodes.len(), LARGE as usize);
        assert_eq!(graph.edges.len(), LARGE as usize - 1);
        assert!(graph.redundant.is_empty());
        assert_eq!(graph.ready, BTreeSet::from([reference("o/r#1")]));
        took
    }

    /// Plans a wide graph of [`LARGE`] tasks, checks it, and returns how
    /// long the plan took.
    fn wide_graph_of_5000() -> Duration {
        // o/r#1 blocks every middle task; the sink waits on all of them and
        // on o/r#1 too, an edge the reduction removes (G5).
        let sink = LARGE + 2;
        let mut bodies: Vec<(u32, String)> = vec![(1, task(1, &[]))];
        bodies.extend((2..=LARGE + 1).map(|n| (n, task(n, &[1]))));
        let all: Vec<u32> = (1..=LARGE + 1).collect();
        bodies.push((sink, task(sink, &all)));
        let observations = tasks(bodies);
        let root = format!("o/r#{sink}");
        let start = Instant::now();
        let outcome = plan(&parameters(&[&root]), &RecordedForge::new(&observations));
        let took = start.elapsed();
        let Ok(Outcome::Planned { graph, .. }) = outcome else {
            panic!("expected a plan, got {outcome:?}");
        };
        assert_eq!(graph.edges.len(), 2 * LARGE as usize + 1);
        assert_eq!(
            graph.redundant,
            BTreeSet::from([Edge {
                from: reference("o/r#1"),
                to: reference(&root),
            }])
        );
        assert_eq!(graph.ready, BTreeSet::from([reference("o/r#1")]));
        took
    }

    /// Plans a cycle of 3,000 tasks and one downstream of it, checks that
    /// G4 reports them all, and returns how long the plan took.
    fn long_cycle() -> Duration {
        // 1 <- 2 <- ... <- 3000 <- 1 is a cycle; 3001 waits on it.
        let n = 3_000;
        let mut bodies: Vec<(u32, String)> = (1..=n)
            .map(|i| (i, task(i, &[if i == 1 { n } else { i - 1 }])))
            .collect();
        bodies.push((n + 1, task(n + 1, &[n])));
        bodies.push((n + 2, task(n + 2, &[])));
        let observations = tasks(bodies);
        let roots = [format!("o/r#{}", n + 1), format!("o/r#{}", n + 2)];
        let start = Instant::now();
        let outcome = plan(
            &parameters(&[&roots[0], &roots[1]]),
            &RecordedForge::new(&observations),
        );
        let took = start.elapsed();
        let Ok(Outcome::Invalid { findings, graph }) = outcome else {
            panic!("expected an invalid run, got {outcome:?}");
        };
        assert!(graph.is_none());
        let cyclic: BTreeSet<u32> = findings
            .iter()
            .filter(|f| f.code == super::Rule::G4.code())
            .map(|f| f.subject.number())
            .collect();
        assert_eq!(cyclic, (1..=n + 1).collect());
        took
    }

    #[test]
    fn d5_a_transferred_listing_seed_that_no_document_names_has_no_finding() {
        // Without roots the seeds come from the home listing (D1). D5 and F5
        // give a transferred reference its own finding only when it is a
        // root that no document names; a listing seed is not a root.
        let observations = Observations {
            home_open_issues: Some(Observed::Value(vec![
                reference("o/r#1"),
                reference("o/r#5"),
            ])),
            home_open_pull_requests: Some(Observed::Value(Vec::new())),
            issues: BTreeMap::from([
                (reference("o/r#1"), owned_issue("o/r#1", &task(1, &[]))),
                (reference("o/r#5"), owned_issue("o/r#9", "Moved here.")),
            ]),
            ..Observations::default()
        };
        let outcome = plan(&parameters(&[]), &RecordedForge::new(&observations));
        let Ok(Outcome::Planned { findings, graph }) = outcome else {
            panic!("expected a plan, got {outcome:?}");
        };
        assert!(findings.is_empty(), "got {findings:?}");
        assert_eq!(graph.ready, BTreeSet::from([reference("o/r#1")]));
    }

    /// Plans with these roots, in this order and reversed, and returns both
    /// results.
    fn both_orders(roots: &[&str], observations: &Observations) -> [Result<Outcome, Missing>; 2] {
        let reversed: Vec<&str> = roots.iter().rev().copied().collect();
        let forge = RecordedForge::new(observations);
        [
            plan(&parameters(roots), &forge),
            plan(&parameters(&reversed), &forge),
        ]
    }

    #[test]
    fn ob5_a_missing_root_is_not_hidden_by_an_unavailable_one() {
        // o/r#1 is unavailable; o/r#2 was not recorded. Both are seeds, so
        // both are read (D1, D2, I5) and the bundle is unusable (OB5),
        // whichever root comes first.
        let observations = Observations {
            home_open_pull_requests: Some(Observed::Value(Vec::new())),
            issues: BTreeMap::from([(
                reference("o/r#1"),
                Observed::Unavailable("HTTP 502".to_owned()),
            )]),
            ..Observations::default()
        };
        for outcome in both_orders(&["o/r#1", "o/r#2"], &observations) {
            assert!(outcome.is_err(), "got {outcome:?}");
        }
    }

    #[test]
    fn ob5_a_missing_prerequisite_is_not_hidden_by_an_unavailable_one() {
        // The root names o/r#2 (unavailable) and o/r#3 (not recorded).
        let mut observations = tasks(vec![(1, task(1, &[2, 3]))]);
        observations.issues.insert(
            reference("o/r#2"),
            Observed::Unavailable("HTTP 502".to_owned()),
        );
        let outcome = plan(&parameters(&["o/r#1"]), &RecordedForge::new(&observations));
        assert!(outcome.is_err(), "got {outcome:?}");
    }

    #[test]
    fn ob5_a_missing_root_is_not_hidden_by_an_unavailable_pull_request_admission() {
        // The pull request's author needs a permission lookup that is
        // unavailable; the root was not recorded.
        let mut closing = pull("o/r#1", Observed::Value(false));
        closing.author = Some(Actor {
            login: "carol".to_owned(),
            actor_type: "User".to_owned(),
        });
        let mut observations = Observations {
            home_open_pull_requests: Some(Observed::Value(vec![closing])),
            ..Observations::default()
        };
        observations.permissions.insert(
            Repo::parse("o/r").expect("repo"),
            BTreeMap::from([(
                "carol".to_owned(),
                Observed::Unavailable("HTTP 502".to_owned()),
            )]),
        );
        let outcome = plan(&parameters(&["o/r#1"]), &RecordedForge::new(&observations));
        assert!(outcome.is_err(), "got {outcome:?}");
    }

    #[test]
    fn d2_the_order_of_the_roots_does_not_change_the_result() {
        // Two unavailable roots with different reasons.
        let observations = Observations {
            home_open_pull_requests: Some(Observed::Value(Vec::new())),
            issues: BTreeMap::from([
                (
                    reference("o/r#1"),
                    Observed::Unavailable("first".to_owned()),
                ),
                (
                    reference("o/r#2"),
                    Observed::Unavailable("second".to_owned()),
                ),
            ]),
            ..Observations::default()
        };
        let [forward, backward] = both_orders(&["o/r#1", "o/r#2"], &observations);
        assert!(
            matches!(forward, Ok(Outcome::Incomplete { .. })),
            "got {forward:?}"
        );
        assert_eq!(forward, backward);
        // Two roots that were not recorded.
        let observations = Observations {
            home_open_pull_requests: Some(Observed::Value(Vec::new())),
            ..Observations::default()
        };
        let [forward, backward] = both_orders(&["o/r#1", "o/r#2"], &observations);
        assert!(forward.is_err(), "got {forward:?}");
        assert_eq!(forward, backward);
    }

    fn pull(closes: &str, draft: Observed<bool>) -> PullRequest {
        PullRequest {
            number: 8,
            repository: Repo::parse("o/r").expect("a repository"),
            head_repository: Repo::parse("o/r"),
            cross_repository: Some(false),
            author: Some(Actor {
                login: "o".to_owned(),
                actor_type: "User".to_owned(),
            }),
            draft,
            closes: vec![reference(closes)],
        }
    }

    #[test]
    fn i5_the_draft_flag_of_a_pull_request_closing_no_node_is_not_read() {
        let mut observations = tasks(vec![(1, task(1, &[]))]);
        observations.home_open_pull_requests = Some(Observed::Value(vec![pull(
            "o/r#9",
            Observed::Unavailable("not a boolean".to_owned()),
        )]));
        let mut owner = BTreeMap::new();
        owner.insert("o".to_owned(), Observed::Value(Some("admin".to_owned())));
        observations
            .permissions
            .insert(Repo::parse("o/r").expect("repo"), owner);
        let outcome = plan(&parameters(&["o/r#1"]), &RecordedForge::new(&observations));
        assert!(
            matches!(outcome, Ok(Outcome::Planned { .. })),
            "got {outcome:?}"
        );
        // The same flag on a pull request that closes an open node is read.
        observations.home_open_pull_requests = Some(Observed::Value(vec![pull(
            "o/r#1",
            Observed::Unavailable("not a boolean".to_owned()),
        )]));
        let outcome = plan(&parameters(&["o/r#1"]), &RecordedForge::new(&observations));
        assert!(
            matches!(outcome, Ok(Outcome::Incomplete { .. })),
            "got {outcome:?}"
        );
    }
}
