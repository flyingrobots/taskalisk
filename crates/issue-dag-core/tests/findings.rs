//! Document findings (flyingrobots/taskalisk#43): every code has a fixture
//! that produces it and one that does not; findings come in a stated order;
//! no message carries body text.
//!
//! Every fixture puts the marker [`MARK`] into values, so a message that
//! copied a value or a line of the body would carry it.

use std::fs;
use std::path::Path;

use issue_dag_core::{
    BODY_WARNINGS, CODES, Finding, IssueRef, LABELS, Label, PLAN_WARNINGS, PROFILE_RULES,
    SHAPE_WARNINGS, Severity, code, findings,
};

/// Marker text placed in the values of every fixture.
const MARK: &str = "ZQXMARK";

/// The address every fixture is judged with.
const ADDRESS: &str = "o/r#1";

fn address() -> IssueRef {
    IssueRef::parse(ADDRESS).expect("the address is a reference")
}

/// A body whose frontmatter block holds `lines`.
fn body(lines: &[&str]) -> String {
    format!(
        "```yaml\n{}\n```\n\n## Outcome\n\nFree text {MARK}.\n",
        lines.join("\n")
    )
}

/// A valid task with a free note carrying the marker, with `edit` applied:
/// each `(key, Some(line))` replaces the line of that key, or is added when
/// the key is not there; `(key, None)` removes it.
fn task(edit: &[(&str, Option<&str>)]) -> String {
    let mut lines = vec![
        ".dag: issue-dag/2".to_owned(),
        format!(".id: {ADDRESS}"),
        ".kind: task".to_owned(),
        ".type: feature".to_owned(),
        ".blocked_by: []".to_owned(),
        format!("note: {MARK}"),
    ];
    for (key, line) in edit {
        let at = lines.iter().position(|l| l.split(':').next() == Some(key));
        match (at, line) {
            (Some(i), Some(l)) => (*l).clone_into(&mut lines[i]),
            (Some(i), None) => {
                lines.remove(i);
            }
            (None, Some(l)) => lines.push((*l).to_owned()),
            (None, None) => {}
        }
    }
    body(&lines.iter().map(String::as_str).collect::<Vec<_>>())
}

fn container(extra: &[&str]) -> String {
    let mut lines = vec![
        ".dag: issue-dag/2",
        ".id: o/r#1",
        ".kind: container",
        "note: ZQXMARK",
    ];
    lines.extend_from_slice(extra);
    body(&lines)
}

/// For one label: a body that produces its code and one that does not.
struct Fixture {
    label: Label,
    produces: String,
    does_not: String,
}

#[allow(clippy::too_many_lines)]
fn fixtures() -> Vec<Fixture> {
    let fx = |label, produces, does_not| Fixture {
        label,
        produces,
        does_not,
    };
    vec![
        fx(
            Label::C4,
            task(&[("note", Some("note: ZQX\u{2028}MARK"))]),
            task(&[]).replace('\n', "\r\n"),
        ),
        fx(
            Label::C6,
            task(&[("-", Some("- ZQXMARK"))]),
            task(&[("#", Some("# ZQXMARK"))]),
        ),
        fx(
            Label::C7,
            task(&[("other", Some("note: ZQXMARK other"))]),
            task(&[("other", Some("other: ZQXMARK other"))]),
        ),
        fx(
            Label::C8,
            task(&[("tags", Some("tags: [ZQXMARK, b"))]),
            task(&[("tags", Some("tags: [ZQXMARK, b]"))]),
        ),
        fx(
            Label::L1,
            task(&[(".blocked_by", Some(".blocked_by: [ZQXMARK#2]"))]),
            task(&[(".blocked_by", Some(".blocked_by: [o/ZQXMARK#2]"))]),
        ),
        fx(
            Label::L2,
            task(&[(".holds", Some(".holds: [ZQXMARK, \"\"]"))]),
            task(&[(".holds", Some(".holds: [ZQXMARK, ZQXMARK]"))]),
        ),
        fx(
            Label::L3,
            task(&[(".meters", Some(".meters: [ZQX MARK*2]"))]),
            task(&[(".meters", Some(".meters: [ZQXMARK*2]"))]),
        ),
        fx(
            Label::L4,
            task(&[(".size_hours", Some(".size_hours: 0"))]),
            task(&[(".size_hours", Some(".size_hours: 1"))]),
        ),
        fx(
            Label::P3,
            task(&[(".dag", Some(".dag: issue-dag/1"))]),
            task(&[(".dag", Some(".dag: issue-dag/ZQXMARK"))]),
        ),
        fx(
            Label::V1,
            task(&[(".dag", Some(".dag: ZQXMARK"))]),
            task(&[(".dag", Some(".dag: issue-dag/3"))]),
        ),
        fx(
            Label::V10,
            task(&[(".size_hours", Some(".size_hours: 9"))]),
            task(&[(".size_hours", Some(".size_hours: 8"))]),
        ),
        fx(
            Label::V2,
            task(&[(".extra", Some(".extra: ZQXMARK"))]),
            task(&[("extra", Some("extra: ZQXMARK"))]),
        ),
        fx(
            Label::V3,
            task(&[(".id", None)]),
            task(&[(".id", Some(".id: O/R#1"))]),
        ),
        fx(
            Label::V4,
            task(&[(".kind", Some(".kind: ZQXMARK"))]),
            task(&[(".kind", Some(".kind: task"))]),
        ),
        fx(
            Label::V5,
            task(&[(".type", Some(".type: ZQXMARK"))]),
            task(&[(".type", Some(".type: bug"))]),
        ),
        fx(
            Label::V6,
            container(&[".children: []", ".blocked_by: [o/r#2]"]),
            container(&[".children: [o/r#2]"]),
        ),
        fx(
            Label::V7,
            task(&[(".blocked_by", Some(".blocked_by: [o/r#1]"))]),
            task(&[(".blocked_by", Some(".blocked_by: [o/r#2]"))]),
        ),
        fx(
            Label::V8,
            task(&[(".status", Some(".status: ZQXMARK"))]),
            task(&[(".status", Some(".status: parked"))]),
        ),
        fx(
            Label::X1,
            task(&[(".id", Some(".id: o/r#2"))]),
            task(&[(".id", Some(".id: O/R#1"))]),
        ),
    ]
}

fn judge(body: &str) -> Vec<Finding> {
    findings(body, &address())
}

fn codes(found: &[Finding]) -> Vec<&'static str> {
    found.iter().map(|f| f.code().as_str()).collect()
}

#[test]
fn every_label_has_a_fixture() {
    let covered: Vec<Label> = fixtures().iter().map(|f| f.label).collect();
    assert_eq!(covered, LABELS);
}

#[test]
fn every_code_has_a_fixture_that_produces_it_and_one_that_does_not() {
    for f in fixtures() {
        let want = code(f.label);
        assert!(
            codes(&judge(&f.produces)).contains(&want),
            "{want}: the producing fixture gives {:?}",
            codes(&judge(&f.produces))
        );
        assert!(
            !codes(&judge(&f.does_not)).contains(&want),
            "{want}: the other fixture gives {:?}",
            codes(&judge(&f.does_not))
        );
    }
}

#[test]
fn codes_are_stable_strings_one_per_label() {
    let all: Vec<&str> = LABELS.iter().map(|l| code(*l)).collect();
    let expected = [
        "format.C4",
        "format.C6",
        "format.C7",
        "format.C8",
        "format.L1",
        "format.L2",
        "format.L3",
        "format.L4",
        "version.P3",
        "format.V1",
        "format.V10",
        "format.V2",
        "format.V3",
        "format.V4",
        "format.V5",
        "format.V6",
        "format.V7",
        "format.V8",
        "profile.X1",
    ];
    assert_eq!(all, expected);
}

/// `CODES` is the one public catalogue: the document codes in `LABELS`
/// order with their severities, then the planning profile's in
/// `PROFILE_RULES` order, all errors, then Taskalisk's body warnings in
/// `BODY_WARNINGS` order (flyingrobots/taskalisk#48), then its shape warnings in
/// `SHAPE_WARNINGS` order (flyingrobots/taskalisk#42), then its plan warnings in
/// `PLAN_WARNINGS` order (flyingrobots/taskalisk#61), each code once.
#[test]
fn codes_catalogue_registers_every_finding_family() {
    let expected: Vec<(&str, Severity)> = LABELS
        .iter()
        .map(|l| {
            let severity = if *l == Label::V10 {
                Severity::Warning
            } else {
                Severity::Error
            };
            (code(*l), severity)
        })
        .chain(PROFILE_RULES.iter().map(|r| (r.code(), Severity::Error)))
        .chain(BODY_WARNINGS.iter().map(|w| (w.code(), Severity::Warning)))
        .chain(SHAPE_WARNINGS.iter().map(|w| (w.code(), Severity::Warning)))
        .chain(PLAN_WARNINGS.iter().map(|c| (*c, Severity::Warning)))
        .collect();
    assert_eq!(CODES, expected.as_slice());
    let mut distinct: Vec<&str> = CODES.iter().map(|(c, _)| *c).collect();
    distinct.sort_unstable();
    distinct.dedup();
    assert_eq!(distinct.len(), CODES.len());
}

/// The one table of codes in the crate docs lists exactly the catalogue
/// `CODES`, in its order, with its severities.
#[test]
fn the_documented_table_matches_the_codes() {
    let source = fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("src/finding.rs"))
        .expect("src/finding.rs is readable");
    let rows: Vec<(String, String)> = source
        .lines()
        .filter_map(|l| l.trim_start().strip_prefix("/// | `"))
        .map(|row| {
            let cells: Vec<&str> = row.split('|').map(str::trim).collect();
            (
                cells[0].trim_end_matches('`').to_owned(),
                cells[2].to_owned(),
            )
        })
        .collect();
    let expected: Vec<(String, String)> = CODES
        .iter()
        .map(|(c, s)| ((*c).to_owned(), s.as_str().to_owned()))
        .collect();
    assert_eq!(rows, expected);
}

#[test]
fn a_violation_is_an_error_and_the_advisory_a_warning() {
    let found = judge(&task(&[(".size_hours", Some(".size_hours: 9"))]));
    assert_eq!(found.len(), 1);
    assert_eq!(found[0].severity(), Severity::Warning);
    let found = judge(&task(&[(".status", Some(".status: ZQXMARK"))]));
    assert_eq!(found.len(), 1);
    assert_eq!(found[0].severity(), Severity::Error);
}

#[test]
fn a_valid_document_without_warnings_and_no_document_have_no_findings() {
    assert_eq!(judge(&task(&[])), []);
    assert_eq!(judge("No frontmatter here, ZQXMARK.\n"), []);
}

#[test]
fn two_violations_give_two_findings_ordered_by_code() {
    let found = judge(&task(&[
        (".status", Some(".status: ZQXMARK")),
        (".kind", None),
    ]));
    assert_eq!(codes(&found), ["format.V4", "format.V8"]);
    // Ordered by the code's text, so V10 comes before V2, and `format.`
    // before `profile.`.
    let found = judge(&task(&[
        (".id", Some(".id: o/r#2")),
        (".status", Some(".status: ZQXMARK")),
    ]));
    assert_eq!(codes(&found), ["format.V8", "profile.X1"]);
}

#[test]
fn findings_of_several_documents_sort_by_subject_then_code() {
    let one = address();
    let two = IssueRef::parse("o/r#2").expect("a reference");
    let mut all = findings(
        &task(&[
            (".id", Some(".id: o/r#2")),
            (".status", Some(".status: x")),
            (".kind", None),
        ]),
        &two,
    );
    all.extend(judge(&task(&[
        (".status", Some(".status: x")),
        (".kind", None),
    ])));
    all.sort();
    let order: Vec<(String, &str)> = all
        .iter()
        .map(|f| (f.subject.to_string(), f.code().as_str()))
        .collect();
    assert_eq!(
        order,
        [
            (one.to_string(), "format.V4"),
            (one.to_string(), "format.V8"),
            (two.to_string(), "format.V4"),
            (two.to_string(), "format.V8"),
        ]
    );
}

#[test]
fn two_runs_give_the_same_report() {
    for f in fixtures() {
        assert_eq!(judge(&f.produces), judge(&f.produces));
    }
}

#[test]
fn the_subject_is_always_the_address() {
    // Valid: the subject is the address the caller named.
    let found = judge(&task(&[
        (".id", Some(".id: O/R#1")),
        (".size_hours", Some(".size_hours: 9")),
    ]));
    assert_eq!(codes(&found), ["format.V10"]);
    assert_eq!(found[0].subject, address());
    // A `.id` naming another issue: X1 runs, filed under the address.
    let found = judge(&task(&[(".id", Some(".id: o/r#5"))]));
    assert_eq!(codes(&found), ["profile.X1"]);
    assert_eq!(found[0].subject, address());
    // Invalid `.id`: the subject is the address.
    let found = judge(&task(&[(".id", Some(".id: ZQXMARK"))]));
    assert_eq!(codes(&found), ["format.L1"]);
    assert_eq!(found[0].subject, address());
}

/// No message carries text from the body: not the marker, not a line.
#[test]
fn no_message_carries_body_text() {
    let mut seen = 0;
    for f in fixtures() {
        for body in [&f.produces, &f.does_not] {
            for finding in judge(body) {
                seen += 1;
                assert!(
                    !finding.message.contains("ZQX") && !finding.message.contains("MARK"),
                    "{}: {:?}",
                    finding.code(),
                    finding.message
                );
                for line in body.lines().map(str::trim).filter(|l| !l.is_empty()) {
                    assert!(
                        !finding.message.contains(line),
                        "{}: {:?} carries the line {line:?}",
                        finding.code(),
                        finding.message
                    );
                }
            }
        }
    }
    assert!(seen >= LABELS.len());
}
