//! Body warnings (flyingrobots/taskalisk#48): Taskalisk's convention for a
//! task body (`skills/taskalisk/WRITING-TASKS.md`). Every code has a fixture
//! that produces it and one that does not; a body filled minimally from each
//! canonical template produces none; findings sort as document findings do;
//! no message carries body or title text.

use std::fs;
use std::path::{Path, PathBuf};

use issue_dag_core::{
    BODY_WARNINGS, BodyWarning, Finding, IssueRef, Severity, body_warnings, findings,
};

/// Marker text placed in every fixture's prose and title.
const MARK: &str = "ZQXMARK";

const ADDRESS: &str = "o/r#1";

fn address() -> IssueRef {
    IssueRef::parse(ADDRESS).expect("the address is a reference")
}

const FRONTMATTER: &str =
    "```yaml\n.dag: issue-dag/2\n.id: o/r#1\n.kind: task\n.type: feature\n.blocked_by: []\n```\n";

/// A valid task body with the three required sections, each `None` section
/// left out and each `Some` section holding that text.
fn task(outcome: Option<&str>, scope: Option<&str>, acceptance: Option<&str>) -> String {
    let section = |heading: &str, text: Option<&str>| {
        text.map_or_else(String::new, |t| format!("\n## {heading}\n{t}\n"))
    };
    [
        FRONTMATTER.to_owned(),
        "\n# Feature\n".to_owned(),
        section("Outcome", outcome),
        section("Scope", scope),
        "\n## Out of scope\nNothing ZQXMARK.\n".to_owned(),
        section("Acceptance", acceptance),
        "\n## 1. Background Context\nMore ZQXMARK. And more.\n".to_owned(),
    ]
    .concat()
}

const OUTCOME: &str = "The parser reads ZQXMARK.";
const SCOPE: &str = "The ZQXMARK module.";
const ACCEPTANCE: &str = "- [ ] ZQXMARK passes.";

fn good() -> String {
    task(Some(OUTCOME), Some(SCOPE), Some(ACCEPTANCE))
}

/// For one warning: a body and title that produce it, and ones that do not.
struct Fixture {
    warning: BodyWarning,
    produces: (String, Option<&'static str>),
    does_not: (String, Option<&'static str>),
}

fn fixtures() -> Vec<Fixture> {
    let fx = |warning, produces, does_not| Fixture {
        warning,
        produces,
        does_not,
    };
    let title = Some("Parse the ZQXMARK carrier");
    vec![
        fx(
            BodyWarning::AcceptanceMissing,
            (task(Some(OUTCOME), Some(SCOPE), None), title),
            (good(), title),
        ),
        fx(
            BodyWarning::OutcomeItems,
            (
                task(
                    Some("- The parser reads ZQXMARK\n- The writer writes it"),
                    Some(SCOPE),
                    Some(ACCEPTANCE),
                ),
                title,
            ),
            (
                task(
                    Some("- The parser reads ZQXMARK, e.g. a block"),
                    Some(SCOPE),
                    Some(ACCEPTANCE),
                ),
                title,
            ),
        ),
        fx(
            BodyWarning::OutcomeMissing,
            (
                task(None, Some(SCOPE), Some(ACCEPTANCE)).replace(
                    "## Out of scope",
                    "## outcome\nThe parser reads ZQXMARK.\n\n## Out of scope",
                ),
                title,
            ),
            (good().replace("## Outcome", "##   Outcome  ##"), title),
        ),
        fx(
            BodyWarning::OutcomeSentences,
            (
                task(
                    Some("The parser reads ZQXMARK. The writer writes it."),
                    Some(SCOPE),
                    Some(ACCEPTANCE),
                ),
                title,
            ),
            (
                task(
                    Some("The parser reads ZQXMARK, e.g. a block, and v1.2 `a. B` too."),
                    Some(SCOPE),
                    Some(ACCEPTANCE),
                ),
                title,
            ),
        ),
        fx(
            BodyWarning::ScopeMissing,
            // `## Out of scope` is not `## Scope`, nor is a level-3 heading.
            (
                task(Some(OUTCOME), None, Some(ACCEPTANCE))
                    .replace("## Out of scope", "### Scope\nZQXMARK.\n\n## Out of scope"),
                title,
            ),
            (good(), title),
        ),
        fx(
            BodyWarning::TitleJoins,
            (good(), Some("Parse ZQXMARK and write it")),
            (good(), Some("Parse the ZQXMARK brand-new carrier")),
        ),
    ]
}

fn judge(body: &str, title: Option<&str>) -> Vec<Finding> {
    body_warnings(body, &address(), title)
}

fn codes(found: &[Finding]) -> Vec<&'static str> {
    found.iter().map(|f| f.code).collect()
}

#[test]
fn every_warning_has_a_fixture() {
    let covered: Vec<BodyWarning> = fixtures().iter().map(|f| f.warning).collect();
    assert_eq!(covered, BODY_WARNINGS);
}

#[test]
fn every_code_has_a_fixture_that_produces_it_and_one_that_does_not() {
    for f in fixtures() {
        let want = f.warning.code();
        let (body, title) = &f.produces;
        let found = codes(&judge(body, *title));
        assert!(
            found.contains(&want),
            "{want}: the producing fixture gives {found:?}"
        );
        let (body, title) = &f.does_not;
        let found = codes(&judge(body, *title));
        assert!(
            !found.contains(&want),
            "{want}: the other fixture gives {found:?}"
        );
    }
}

#[test]
fn codes_are_stable_strings_in_text_order() {
    let all: Vec<&str> = BODY_WARNINGS.iter().map(|w| w.code()).collect();
    assert_eq!(
        all,
        [
            "taskalisk.acceptance-missing",
            "taskalisk.outcome-items",
            "taskalisk.outcome-missing",
            "taskalisk.outcome-sentences",
            "taskalisk.scope-missing",
            "taskalisk.title-joins",
        ]
    );
    let mut sorted = BODY_WARNINGS;
    sorted.sort_unstable();
    assert_eq!(sorted, BODY_WARNINGS);
}

#[test]
fn every_finding_is_a_warning_filed_under_the_address() {
    let found = judge(&task(None, None, None), Some("A and B; C"));
    assert_eq!(
        codes(&found),
        [
            "taskalisk.acceptance-missing",
            "taskalisk.outcome-missing",
            "taskalisk.scope-missing",
            "taskalisk.title-joins",
        ]
    );
    for f in &found {
        assert_eq!(f.severity, Severity::Warning);
        assert_eq!(f.subject, address());
    }
}

#[test]
fn a_title_joined_by_a_semicolon_or_an_and_in_any_case_warns() {
    for title in [
        "Parse ZQXMARK; write it",
        "Parse ZQXMARK AND write it",
        "A\tand\tB",
    ] {
        assert_eq!(
            codes(&judge(&good(), Some(title))),
            ["taskalisk.title-joins"],
            "{title}"
        );
    }
    for title in [
        "Handle ZQXMARK bands",
        "Andrew's ZQXMARK",
        "Parse `a;b` ZQXMARK",
    ] {
        assert_eq!(
            codes(&judge(&good(), Some(title))),
            [] as [&str; 0],
            "{title}"
        );
    }
}

#[test]
fn without_a_title_the_title_check_is_skipped() {
    assert_eq!(judge(&good(), None), []);
}

#[test]
fn both_outcome_signs_can_fire_together() {
    let body = task(
        Some("One ZQXMARK. Two.\n\n- a\n- b"),
        Some(SCOPE),
        Some(ACCEPTANCE),
    );
    assert_eq!(
        codes(&judge(&body, None)),
        ["taskalisk.outcome-items", "taskalisk.outcome-sentences"]
    );
}

#[test]
fn one_item_of_two_sentences_is_two_sentences() {
    let body = task(
        Some("- The parser reads ZQXMARK. The writer writes it."),
        Some(SCOPE),
        Some(ACCEPTANCE),
    );
    assert_eq!(codes(&judge(&body, None)), ["taskalisk.outcome-sentences"]);
}

#[test]
fn a_numbered_list_counts_its_items() {
    for list in [
        "1. The parser\n2. The writer",
        "1) The parser\n2) The writer",
    ] {
        let body = task(Some(list), Some(SCOPE), Some(ACCEPTANCE));
        assert_eq!(
            codes(&judge(&body, None)),
            ["taskalisk.outcome-items"],
            "{list}"
        );
    }
    let body = task(
        Some("1. The parser reads ZQXMARK."),
        Some(SCOPE),
        Some(ACCEPTANCE),
    );
    assert_eq!(judge(&body, None), []);
}

/// A missing section's message names the exact heading it requires, so a
/// decorated heading such as `## Outcome:` explains itself.
#[test]
fn a_missing_section_message_names_the_exact_heading() {
    let body = task(Some(OUTCOME), Some(SCOPE), Some(ACCEPTANCE))
        .replace("## Outcome", "## Outcome:")
        .replace("## Scope", "## **Scope**")
        .replace("## Acceptance", "## Acceptance criteria");
    let found = judge(&body, None);
    assert_eq!(
        codes(&found),
        [
            "taskalisk.acceptance-missing",
            "taskalisk.outcome-missing",
            "taskalisk.scope-missing",
        ]
    );
    for (finding, name) in found.iter().zip(["Acceptance", "Outcome", "Scope"]) {
        assert_eq!(
            finding.message,
            format!("the body has no `## {name}` heading (exact text, level 2)")
        );
    }
}

#[test]
fn a_second_paragraph_is_a_second_sentence() {
    let body = task(
        Some("The parser reads ZQXMARK\n\nThe writer writes it"),
        Some(SCOPE),
        Some(ACCEPTANCE),
    );
    assert_eq!(codes(&judge(&body, None)), ["taskalisk.outcome-sentences"]);
    // One sentence wrapped over two lines is one sentence.
    let body = task(
        Some("The parser reads\nZQXMARK."),
        Some(SCOPE),
        Some(ACCEPTANCE),
    );
    assert_eq!(judge(&body, None), []);
}

#[test]
fn headings_in_code_fences_and_comments_do_not_count() {
    let body =
        format!("{FRONTMATTER}\n```text\n## Outcome\n## Scope\n```\n<!--\n## Acceptance\n-->\n");
    assert_eq!(
        codes(&judge(&body, None)),
        [
            "taskalisk.acceptance-missing",
            "taskalisk.outcome-missing",
            "taskalisk.scope-missing",
        ]
    );
    // Prose inside a comment in the Outcome is not a sentence.
    let body = task(
        Some("<!-- A note. Another. -->\nThe parser reads ZQXMARK."),
        Some(SCOPE),
        Some(ACCEPTANCE),
    );
    assert_eq!(judge(&body, None), []);
}

#[test]
fn crlf_bodies_are_read_the_same() {
    assert_eq!(judge(&good().replace('\n', "\r\n"), None), []);
    let body = task(None, Some(SCOPE), Some(ACCEPTANCE)).replace('\n', "\r\n");
    assert_eq!(codes(&judge(&body, None)), ["taskalisk.outcome-missing"]);
}

#[test]
fn only_valid_task_documents_are_checked() {
    let container =
        "```yaml\n.dag: issue-dag/2\n.id: o/r#1\n.kind: container\n.children: [o/r#2]\n```\n";
    assert_eq!(judge(container, Some("A and B")), []);
    assert_eq!(judge("No frontmatter, ZQXMARK.\n", Some("A and B")), []);
    // An invalid document reports no warnings, as with document findings.
    let invalid = task(None, None, None).replace(".type: feature", ".type: ZQXMARK");
    assert_eq!(judge(&invalid, Some("A and B")), []);
    assert_ne!(findings(&invalid, &address()), []);
}

#[test]
fn two_runs_give_the_same_report() {
    for f in fixtures() {
        let (body, title) = &f.produces;
        assert_eq!(judge(body, *title), judge(body, *title));
    }
}

#[test]
fn findings_of_several_documents_sort_by_subject_then_code() {
    let two = IssueRef::parse("o/r#2").expect("a reference");
    let mut all = body_warnings(
        &task(None, None, Some(ACCEPTANCE)).replace(".id: o/r#1", ".id: o/r#2"),
        &two,
        None,
    );
    all.extend(judge(&task(None, Some(SCOPE), None), Some("A; B")));
    all.sort();
    let order: Vec<(String, &str)> = all
        .iter()
        .map(|f| (f.subject.to_string(), f.code))
        .collect();
    assert_eq!(
        order,
        [
            ("o/r#1".to_owned(), "taskalisk.acceptance-missing"),
            ("o/r#1".to_owned(), "taskalisk.outcome-missing"),
            ("o/r#1".to_owned(), "taskalisk.title-joins"),
            ("o/r#2".to_owned(), "taskalisk.outcome-missing"),
            ("o/r#2".to_owned(), "taskalisk.scope-missing"),
        ]
    );
}

/// No message carries text from the body or the title.
#[test]
fn no_message_carries_body_or_title_text() {
    let mut seen = 0;
    for f in fixtures() {
        for (body, title) in [&f.produces, &f.does_not] {
            for finding in judge(body, *title) {
                seen += 1;
                assert!(
                    !finding.message.contains(MARK)
                        && !finding.message.contains("ZQX")
                        && !finding.message.contains("MARK"),
                    "{}: {:?}",
                    finding.code,
                    finding.message
                );
                let lines = body.lines().chain(title.iter().copied());
                for line in lines.map(str::trim).filter(|l| l.len() > 3) {
                    assert!(
                        !finding.message.contains(line),
                        "{}: {:?} carries {line:?}",
                        finding.code,
                        finding.message
                    );
                }
            }
        }
    }
    assert!(seen >= BODY_WARNINGS.len());
}

fn templates() -> Vec<PathBuf> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../skills/taskalisk/templates/issue");
    let mut paths: Vec<PathBuf> = fs::read_dir(&dir)
        .expect("the template directory is readable")
        .map(|e| e.expect("a directory entry").path())
        .filter(|p| p.extension().is_some_and(|x| x == "md"))
        .collect();
    paths.sort();
    paths
}

/// A template as an issue body, filled minimally: the issue form's own
/// front matter removed, `.id` set to the address, and the Outcome
/// placeholder replaced by one sentence.
fn fill(template: &str) -> String {
    let body = template
        .strip_prefix("---\n")
        .and_then(|rest| rest.split_once("\n---\n"))
        .map_or(template, |(_, body)| body);
    let placeholder =
        "One sentence, with one subject and one verb. If it needs \"and\", it is two issues.";
    assert!(body.contains(placeholder), "the Outcome placeholder moved");
    body.replace("OWNER/REPO#NEW", ADDRESS)
        .replace(placeholder, "The parser reads the carrier.")
}

#[test]
fn a_body_from_each_canonical_template_has_no_warnings() {
    let paths = templates();
    assert_eq!(paths.len(), 7, "{paths:?}");
    for path in paths {
        let template = fs::read_to_string(&path).expect("a template is readable");
        let body = fill(&template);
        assert_eq!(findings(&body, &address()), [], "{}", path.display());
        assert_eq!(
            judge(&body, Some("Parse the carrier")),
            [],
            "{}",
            path.display()
        );
    }
}
