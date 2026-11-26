//! `taskalisk edit`: add or remove one edge in a child issue's
//! `.blocked_by` (flyingrobots/taskalisk#1, the edge-edit contract E1 to
//! E10).
//!
//! The order is the contract's. The edit is checked before any write: the
//! scope, the child's admission and document, and the plan with the edit
//! applied in memory against the plan without it, the child included even
//! when the roots do not reach it (E1 to E6). A failed lookup stops the run
//! there. Then the account the write is made as must be admitted (E7), and
//! the child is read again, through a forge that has read nothing yet: a
//! change to its address, its body or the admission of its editors refuses
//! the write (E7). Then one `PATCH` replaces the body. A write that fails is
//! reported with its outcome unknown, never retried and never undone (E9).
//!
//! This is an optimistic check, not a lock (E8): GitHub documents no
//! conditional update of an issue, so an edit made between the final
//! reread and the write can be lost, and a change to another issue after
//! the checks can make the graph invalid; the next plan reports it.

use issue_dag_core::{
    Checked, Conflict, EdgeEdit, EditRefusal, ForgeWrite, IssueRef, NotFound, Observed, Parameters,
    Proposed, Refusal, check_edit, plan, recheck, writer_admitted,
};
use issue_dag_gh::{GhForge, WriteFailure, repository_of};
use serde_json::{Value, json};

use crate::cli::{self, Arguments, Failure, one_sentence};
use crate::parley::Run;

/// What `edit --help` says the command does.
pub const INTENT: &str = "Add or remove one edge in a child issue's frontmatter .blocked_by: the plan with the edit is compiled in memory and checked first, the child is reread just before the one write, and nothing is restored or retried (--add-edge, --remove-edge)";

/// The result schema `edit --help` describes besides the plan's.
pub const DESCRIBED: [(&str, &str); 1] = [(
    "taskalisk.edge_edit",
    include_str!("../../../skills/taskalisk/schemas/taskalisk.edge_edit.schema.json"),
)];

/// The `--reason` of an edit that gives none, as in 1.x.
const DEFAULT_REASON: &str = "taskalisk edge update";

/// The phase of every error of an edit, before or at the write.
const PHASE: &str = "edge_edit";

/// What `edit` reads and writes.
pub fn effects(reads: &[&str]) -> Value {
    let mut reads: Vec<&str> = reads.to_vec();
    reads.push("github:the authenticated account (gh api user)");
    json!({
        "reads": reads,
        "writes": ["github:issue-body (the child's .blocked_by line)"],
        "network": true,
        "idempotent": true,
    })
}

/// The edge an `edit` adds or removes, checked before the run starts.
#[derive(Debug)]
pub struct Request {
    add: bool,
    parent: IssueRef,
    child: IssueRef,
    /// The edge as given.
    text: String,
}

impl Request {
    /// The one `--add-edge` or `--remove-edge` (`true` for add) with its
    /// value `owner/repo#parent->owner/repo#child`.
    ///
    /// # Errors
    ///
    /// Why the edge cannot be edited: none or more than one given, a
    /// reference that is not `owner/repo#N`, or a self-edge (E1).
    pub fn parse(edges: &[(bool, String)]) -> Result<Self, String> {
        let [(add, text)] = edges else {
            return Err(if edges.is_empty() {
                "edit needs --add-edge or --remove-edge".to_owned()
            } else {
                "--add-edge and --remove-edge are mutually exclusive, and each is given once"
                    .to_owned()
            });
        };
        let invalid = || {
            format!(
                "Invalid edge syntax (expected 'owner/repo#parent->owner/repo#child'; bare numbers are not allowed): {text}"
            )
        };
        let (parent, child) = text.split_once("->").ok_or_else(invalid)?;
        let (Some(parent), Some(child)) = (IssueRef::parse(parent), IssueRef::parse(child)) else {
            return Err(invalid());
        };
        if parent == child {
            return Err(format!("Self-edge rejected: {child}"));
        }
        Ok(Self {
            add: *add,
            parent,
            child,
            text: text.clone(),
        })
    }

    /// The edit, as the resolved question's `options.edge` records it.
    pub fn resolved(&self, reason: Option<&str>) -> Value {
        json!({
            "op": if self.add { "add" } else { "remove" },
            "edge": self.text,
            "reason": reason.unwrap_or(DEFAULT_REASON),
        })
    }

    fn edit(&self) -> EdgeEdit {
        if self.add {
            EdgeEdit::Add(self.parent.clone())
        } else {
            EdgeEdit::Remove(self.parent.clone())
        }
    }

    /// The error line of an edit refused for `code`, naming the child.
    fn refuse(&self, run: &mut Run<'_>, code: &str, problem: &str, remedy: &str, extra: Value) {
        let mut detail = json!({
            "source": format!("edge {}->{}", self.parent, self.child),
            "error": problem,
            "phase": PHASE,
            "parent": self.parent.to_string(),
            "child": self.child.to_string(),
        });
        if let (Some(detail), Value::Object(extra)) = (detail.as_object_mut(), extra) {
            detail.extend(extra);
        }
        run.error(
            code,
            &one_sentence(problem),
            Some(remedy),
            Some(false),
            Some(detail),
        );
    }
}

/// Every failed `gh` read of `forge`, as errors of the edit; whether there
/// was one.
fn failed(run: &mut Run<'_>, forge: &GhForge) -> bool {
    let failures = forge.failures();
    for failure in &failures {
        Failure::gh(failure).report_in(run, PHASE);
    }
    !failures.is_empty()
}

/// Checks the edit, writes it once, and plans the validated proposal.
pub fn edit_live(
    run: &mut Run<'_>,
    arguments: &Arguments,
    request: &Request,
    repo_dir: &std::path::Path,
) {
    let home = match repository_of("gh", &[], repo_dir) {
        Ok(home) => home,
        Err(error) => return Failure::gh(&error).report_in(run, PHASE),
    };
    run.step(
        &format!("the home repository is {home}"),
        "gh resolves it from --repo; references compare in this lowercase spelling",
        None,
    );
    let branches = match cli::branch_names(repo_dir) {
        Ok(branches) => branches,
        Err(error) => return Failure::git(&error).report(run),
    };
    let parameters = cli::parameters(arguments, home.clone());
    let forge = GhForge::new(home.clone()).current_dir(repo_dir);
    let checked = check_edit(&parameters, &forge, &request.child, &request.edit());
    // A failed read is never an answer: the edit stops before any write.
    if failed(run, &forge) {
        return;
    }
    let checked = match checked {
        Ok(checked) => checked,
        Err(refusal) => return refuse(run, request, &refusal),
    };
    if checked.rewrite.changed {
        run.step(
            &format!("checked the edit of {}", request.child),
            "the plan with the edit, compiled in memory with the child among the seeds, has no cycle, violation, out-of-scope reference or unknown prerequisite that the plan without it lacks (E6)",
            None,
        );
        let fresh = GhForge::new(home).current_dir(repo_dir);
        if !write(run, &parameters, &forge, &fresh, request, &checked) {
            return;
        }
    } else {
        run.step(
            &format!("the edit leaves the body of {} unchanged", request.child),
            "an unchanged body is not written (E5), so no writer is asked for",
            None,
        );
    }
    run.result(json!({
        "event": "edge_edit",
        "_schema": {"id": "taskalisk.edge_edit", "version": "1.0.0"},
        "type": if request.add { "add_blocked_by" } else { "remove_blocked_by" },
        "parent": request.parent.to_string(),
        "child": request.child.to_string(),
        "changed": checked.rewrite.changed,
        "reason": arguments.reason.as_deref().unwrap_or(DEFAULT_REASON),
        "recorded_in": format!("frontmatter of {} (the issue edit history is the ledger)", request.child),
    }));
    // The plan of the run's own roots, over the proposal that was checked
    // and written: not a new observation of GitHub after the write.
    let proposed = Proposed::new(&forge, &request.child, Some(checked.rewrite.body.clone()));
    let outcome = plan(&parameters, &proposed);
    let failures = forge.failures();
    let observations = forge.observations();
    let display = cli::display(forge.shown(), &observations, &parameters, &branches);
    if failures.is_empty() {
        cli::observed(run, &observations, &display);
    }
    run.step(
        "planned the validated proposal",
        "the plan after an edit is computed over the bodies the checks read, with the child's new body; a change made on GitHub since then shows in the next plan (E8)",
        None,
    );
    match outcome {
        Ok(outcome) => {
            cli::record(run, &parameters, &outcome);
            cli::conclude(run, &parameters, &outcome, &failures, &display);
        }
        Err(missing) => run.error(
            "plan.observation_missing",
            &format!("the planner read a slot the forge did not record: {missing}"),
            Some("report this defect with the receipt"),
            Some(false),
            None,
        ),
    }
}

/// E7 and the write: the writer's admission, the final reread through
/// `fresh`, and one `PATCH`. Whether the body was written.
fn write(
    run: &mut Run<'_>,
    parameters: &Parameters,
    forge: &GhForge,
    fresh: &GhForge,
    request: &Request,
    checked: &Checked,
) -> bool {
    let child = &request.child;
    let Observed::Value(writer) = forge.writer() else {
        failed(run, forge);
        return false;
    };
    match writer_admitted(parameters, forge, child, &writer) {
        Ok(true) => {}
        Ok(false) => {
            request.refuse(
                run,
                "edge.writer_untrusted",
                &format!(
                    "the account {} is not admitted to write {child} under the trust policy",
                    writer.login
                ),
                "write as an account the trust policy admits in the child's repository; a bot needs an explicit --trust entry such as name[bot]",
                json!({"writer": writer.login}),
            );
            return false;
        }
        Err(undecided) => {
            if !failed(run, forge) {
                refuse(run, request, &EditRefusal::from(undecided));
            }
            return false;
        }
    }
    run.step(
        &format!("the writer {} is admitted", writer.login),
        "the account the write is made as passes the same trust policy as the issues it plans from (E7)",
        None,
    );
    let reread = recheck(parameters, fresh, checked);
    if failed(run, fresh) {
        return false;
    }
    if let Err(refusal) = reread {
        refuse(run, request, &refusal);
        return false;
    }
    run.step(
        &format!("reread {child} just before the write"),
        "its address, its body and the admission of its editors are what the checks validated (E7); an edit made after this reread can still be lost, because GitHub documents no conditional update of an issue (E8)",
        None,
    );
    if let Err(failure) = forge.replace_body(child, &checked.rewrite.body) {
        report_write_failure(run, request, &failure);
        return false;
    }
    run.step(
        &format!("wrote the body of {child}"),
        "an edge edit replaces the whole issue body; only its .blocked_by line differs (the issue edit history is the ledger)",
        None,
    );
    true
}

fn report_write_failure(run: &mut Run<'_>, request: &Request, failure: &WriteFailure) {
    run.error(
        WriteFailure::CODE,
        &one_sentence(&format!("{failure}")),
        Some("read the child's body and edit history on GitHub before editing again: the write may have been applied; it was neither retried nor undone"),
        Some(false),
        Some(json!({
            "source": failure.source,
            "error": failure.detail,
            "phase": PHASE,
            "child": request.child.to_string(),
            "write_outcome": "unknown",
        })),
    );
}

/// The error line of a refused edit (E10): nothing was written.
fn refuse(run: &mut Run<'_>, request: &Request, refusal: &EditRefusal) {
    let child = &request.child;
    let none = json!({});
    match refusal {
        EditRefusal::OutOfScope(reference) => request.refuse(
            run,
            "edge.out_of_scope",
            &format!("{reference} is outside the trusted repositories"),
            "add --trust-owner or --trust-repo, or choose an issue inside the scope",
            none,
        ),
        EditRefusal::PullRequest => request.refuse(
            run,
            "edge.child_not_issue",
            &format!("{child} is a pull request, not an issue"),
            "name the pull request's issue as the child",
            none,
        ),
        EditRefusal::Transferred(to) => request.refuse(
            run,
            "edge.child_not_issue",
            &format!("{child} was transferred to {to}"),
            "name the issue at its new address as the child",
            json!({"transferred_to": to.to_string()}),
        ),
        EditRefusal::Untrusted => request.refuse(
            run,
            "edge.child_untrusted",
            &format!("{child} is untrusted: its author or an editor of its body is not admitted"),
            "never write into a stranger's issue; a trusted person files their own issue",
            none,
        ),
        EditRefusal::Document(refusal) => document(run, request, refusal),
        EditRefusal::Cycle(nodes) => request.refuse(
            run,
            "edge.cycle",
            &format!(
                "the edge {}->{child} would close a cycle of .blocked_by edges",
                request.parent
            ),
            "split the shared foundation into a predecessor issue, or remove the edge that closes the cycle",
            json!({"cyclic_nodes": nodes.iter().map(ToString::to_string).collect::<Vec<_>>()}),
        ),
        EditRefusal::NewFindings(findings) => request.refuse(
            run,
            "edge.graph_invalid",
            &format!(
                "the edge {}->{child} would bring {} error finding(s) into the plan that it does not have",
                request.parent,
                findings.len()
            ),
            "fix the issues the findings name first, then edit again",
            json!({"findings": findings.iter().map(|f| json!({
                "subject": f.subject.to_string(),
                "code": f.code().as_str(),
                "concerns": f.concerns.as_ref().map(ToString::to_string),
            })).collect::<Vec<_>>()}),
        ),
        EditRefusal::Conflict(conflict) => {
            let (what, why) = match conflict {
                Conflict::Address => ("address", "it no longer resolves to the same issue"),
                Conflict::Body => ("body", "its body differs from the body that was checked"),
                Conflict::Trust => (
                    "trust",
                    "its author or an editor of its body is no longer admitted",
                ),
            };
            request.refuse(
                run,
                "edge.conflict",
                &format!("{child} changed after it was checked: {why}; nothing was written"),
                "read the issue again, and run the edit again only if it is still wanted",
                json!({"conflict": what}),
            );
        }
        EditRefusal::Incomplete { unavailable, cause } => incomplete(run, unavailable, *cause),
        EditRefusal::Missing(missing) => run.error(
            "plan.observation_missing",
            &format!("the edit read a slot the forge did not record: {missing}"),
            Some("report this defect with the receipt"),
            Some(false),
            None,
        ),
        EditRefusal::Rejected(rejection) => cli::reject(run, rejection),
    }
}

/// An incomplete edit (E10): an observation it needs is unavailable, with
/// the not-found cause when one was recorded, reported as a plan reports it.
fn incomplete(run: &mut Run<'_>, unavailable: &str, cause: Option<NotFound>) {
    let mut detail = json!({"source": "gh", "error": unavailable, "phase": PHASE});
    let code = cause.map_or("gh.response_invalid", |cause| {
        detail["rule"] = json!(cause.label());
        detail["not_found"] = json!(cause.as_str());
        "issue.not_found"
    });
    run.error(
        code,
        &one_sentence(unavailable),
        Some("fix the reference or the read, then edit again; nothing was written"),
        Some(false),
        Some(detail),
    );
}

fn document(run: &mut Run<'_>, request: &Request, refusal: &Refusal) {
    let child = &request.child;
    let (code, problem, remedy, extra) = match refusal {
        Refusal::NoDocument => (
            "edge.child_frontmatter_missing",
            format!("{child} has no issue-dag frontmatter"),
            "give the child valid issue-dag/2 task frontmatter first",
            json!({}),
        ),
        Refusal::Invalid(labels) => (
            "edge.child_frontmatter_invalid",
            format!("{child} has invalid task frontmatter"),
            "fix the child's frontmatter first; a plan's frontmatter.violation findings say how",
            json!({"rules": labels.iter().map(ToString::to_string).collect::<Vec<_>>()}),
        ),
        Refusal::NotATask => (
            "edge.child_frontmatter_invalid",
            format!("{child} is not a task"),
            "only a task has .blocked_by; name a task as the child",
            json!({}),
        ),
        Refusal::SelfEdge | Refusal::BlockedByLines(_) => (
            "edge.rewrite_impossible",
            format!("the .blocked_by line of {child} cannot be rewritten"),
            "the child's frontmatter needs exactly one .blocked_by line",
            json!({}),
        ),
    };
    request.refuse(run, code, &problem, remedy, extra);
}

#[cfg(test)]
mod tests {
    use super::Request;

    fn parse(edges: &[(bool, &str)]) -> Result<Request, String> {
        let edges: Vec<(bool, String)> = edges.iter().map(|(a, t)| (*a, (*t).to_owned())).collect();
        Request::parse(&edges)
    }

    #[test]
    fn an_edge_is_one_parent_and_one_child() {
        let request = parse(&[(true, "O/R#1->o/r#5")]).expect("an edge");
        assert_eq!(request.parent.to_string(), "o/r#1");
        assert_eq!(request.child.to_string(), "o/r#5");
        assert_eq!(request.resolved(None)["reason"], "taskalisk edge update");
        assert!(parse(&[]).is_err());
        assert!(parse(&[(true, "o/r#1->o/r#5"), (false, "o/r#1->o/r#5")]).is_err());
        assert!(parse(&[(true, "1->5")]).is_err());
        assert!(parse(&[(true, "o/r#1->o/r#5->o/r#6")]).is_err());
        assert!(parse(&[(false, "o/r#5->O/R#5")]).is_err());
    }
}
