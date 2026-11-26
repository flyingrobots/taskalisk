//! The `.blocked_by` rewrite of the edge-edit contract (rule E4).

use crate::label::Label;
use crate::reference::IssueRef;

/// One edge edit on a child's `.blocked_by` (rule E1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum EdgeEdit {
    /// Make the parent a prerequisite of the child.
    Add(IssueRef),
    /// Take every occurrence of the parent out of the child's `.blocked_by`.
    Remove(IssueRef),
}

/// Why a rewrite is refused.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Refusal {
    /// The body has no frontmatter block.
    NoDocument,
    /// The block does not have exactly one `.blocked_by` line; the count.
    BlockedByLines(usize),
    /// The body is not a valid task document for the address; the labels
    /// of its violations.
    Invalid(Vec<Label>),
    /// The parent equals the child (rule E1).
    SelfEdge,
}

/// A rewritten body.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Rewrite {
    /// The new body.
    pub body: String,
    /// Whether it differs from the old body; when it does not, nothing is
    /// to be written (rule E5).
    pub changed: bool,
}

/// Rewrites the `.blocked_by` line of a valid task document, judged with its
/// issue's address, and changes no other character of the body (rule E4).
///
/// # Errors
///
/// Returns a [`Refusal`] when the body is not a valid task document for that
/// address, when its block does not have exactly one `.blocked_by` line, or
/// when the parent equals the child.
// RED: a stub until the rewrite is written.
#[allow(clippy::missing_const_for_fn)]
pub fn rewrite_blocked_by(
    body: &str,
    address: &IssueRef,
    edit: &EdgeEdit,
) -> Result<Rewrite, Refusal> {
    let _ = (body, address, edit);
    Err(Refusal::NoDocument)
}

#[cfg(test)]
mod tests {
    use super::{EdgeEdit, Refusal, rewrite_blocked_by};
    use crate::label::Label;
    use crate::reference::IssueRef;

    fn r(text: &str) -> IssueRef {
        IssueRef::parse(text).expect("a reference")
    }

    fn task(blocked_by_line: &str, eol: &str) -> String {
        [
            "```yaml ",
            ".dag: issue-dag/2",
            "# a comment  ",
            ".id: O/R#1",
            ".kind:   task",
            ".type: 'bug'",
            blocked_by_line,
            "area: x # not a comment",
            "```",
            "",
            "## Outcome",
            "",
            "Free text, .blocked_by: [o/r#9] is not a key here.",
        ]
        .join(eol)
            + eol
    }

    fn add(body: &str, parent: &str) -> Result<super::Rewrite, Refusal> {
        rewrite_blocked_by(body, &r("o/r#1"), &EdgeEdit::Add(r(parent)))
    }

    fn remove(body: &str, parent: &str) -> Result<super::Rewrite, Refusal> {
        rewrite_blocked_by(body, &r("o/r#1"), &EdgeEdit::Remove(r(parent)))
    }

    #[test]
    fn add_appends_the_parent_in_canonical_form_and_changes_only_that_line() {
        let old = task(".blocked_by:[ O/R#2 ,\"o/s#3\"]   ", "\n");
        let new = add(&old, "My.Org/Re_po#4").expect("an edit");
        assert_eq!(
            new.body,
            task(".blocked_by: [o/r#2, o/s#3, my.org/re_po#4]", "\n")
        );
        assert!(new.changed);
    }

    #[test]
    fn add_to_an_empty_list() {
        let new = add(&task(".blocked_by: []", "\n"), "o/r#2").expect("an edit");
        assert_eq!(new.body, task(".blocked_by: [o/r#2]", "\n"));
    }

    #[test]
    fn add_of_an_existing_reference_keeps_the_list() {
        let old = task(".blocked_by: [o/r#2, o/r#3]", "\n");
        let new = add(&old, "O/R#2").expect("an edit");
        assert_eq!(new.body, old);
        assert!(!new.changed, "an unchanged body is a no-op (E5)");
    }

    #[test]
    fn add_of_an_existing_reference_still_canonicalises_the_line() {
        let new = add(&task(".blocked_by: [O/R#2]", "\n"), "o/r#2").expect("an edit");
        assert_eq!(new.body, task(".blocked_by: [o/r#2]", "\n"));
        assert!(new.changed);
    }

    #[test]
    fn remove_takes_out_every_occurrence() {
        let old = task(".blocked_by: [o/r#2, o/r#3, O/R#2]", "\n");
        let new = remove(&old, "o/r#2").expect("an edit");
        assert_eq!(new.body, task(".blocked_by: [o/r#3]", "\n"));
        assert!(new.changed);
    }

    #[test]
    fn remove_of_the_last_reference_writes_an_empty_list() {
        let new = remove(&task(".blocked_by: [o/r#2]", "\n"), "o/r#2").expect("an edit");
        assert_eq!(new.body, task(".blocked_by: []", "\n"));
    }

    #[test]
    fn remove_of_an_absent_reference_is_a_no_op() {
        let old = task(".blocked_by: [o/r#2]", "\n");
        let new = remove(&old, "o/r#7").expect("an edit");
        assert_eq!(new.body, old);
        assert!(!new.changed);
    }

    #[test]
    fn crlf_line_ends_are_preserved() {
        let old = task(".blocked_by: [o/r#2]", "\r\n");
        let new = add(&old, "o/r#3").expect("an edit");
        assert_eq!(new.body, task(".blocked_by: [o/r#2, o/r#3]", "\r\n"));
        let new = remove(&old, "o/r#2").expect("an edit");
        assert_eq!(new.body, task(".blocked_by: []", "\r\n"));
    }

    #[test]
    fn a_body_without_frontmatter_is_refused() {
        assert_eq!(add("No block here.\n", "o/r#2"), Err(Refusal::NoDocument));
    }

    #[test]
    fn two_blocked_by_lines_are_refused() {
        let old = task(".blocked_by: []\n.blocked_by: [o/r#2]", "\n");
        assert_eq!(add(&old, "o/r#3"), Err(Refusal::BlockedByLines(2)));
    }

    #[test]
    fn no_blocked_by_line_is_refused() {
        let old = task("note: none", "\n");
        assert_eq!(add(&old, "o/r#3"), Err(Refusal::BlockedByLines(0)));
        let container =
            "```yaml\n.dag: issue-dag/2\n.id: o/r#1\n.kind: container\n.children: []\n```\n";
        assert_eq!(add(container, "o/r#3"), Err(Refusal::BlockedByLines(0)));
    }

    #[test]
    fn an_invalid_document_is_refused() {
        let old = task(".blocked_by: [o/r#2", "\n");
        assert_eq!(
            add(&old, "o/r#3"),
            Err(Refusal::Invalid(vec![Label::C8, Label::V5]))
        );
    }

    #[test]
    fn a_document_naming_another_issue_is_refused() {
        let old = task(".blocked_by: []", "\n");
        assert_eq!(
            rewrite_blocked_by(&old, &r("o/r#5"), &EdgeEdit::Add(r("o/r#2"))),
            Err(Refusal::Invalid(vec![Label::X1]))
        );
    }

    #[test]
    fn a_parent_equal_to_the_child_is_refused() {
        let old = task(".blocked_by: []", "\n");
        assert_eq!(add(&old, "O/R#1"), Err(Refusal::SelfEdge));
        assert_eq!(remove(&old, "o/r#1"), Err(Refusal::SelfEdge));
    }
}
