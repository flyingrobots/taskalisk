//! A finding's code is a [`Code`] (flyingrobots/taskalisk#60): a value with
//! no public constructor, so every finding carries a code of the catalogue
//! [`CODES`], and its severity is the one the catalogue gives that code.
//! The code's text, which is what any serialised form carries, is unchanged.
//!
//! That a code outside the catalogue cannot be built is checked by the
//! `compile_fail` examples on [`Code`].

use std::collections::BTreeSet;

use issue_dag_core::{
    BODY_WARNINGS, CODES, Code, Finding, IssueRef, LABELS, PROFILE_RULES, Rule, Severity,
    body_warnings, findings,
};

fn subject() -> IssueRef {
    IssueRef::parse("o/r#1").expect("a reference")
}

/// `Code::all` is the catalogue: each code once, in `CODES` order, with its
/// text and its severity.
#[test]
fn every_code_is_a_catalogue_entry_with_its_severity() {
    let all: Vec<(&str, Severity)> = Code::all().map(|c| (c.as_str(), c.severity())).collect();
    assert_eq!(all.as_slice(), CODES);
}

/// The text a code shows and compares as is the catalogue's, so a report
/// that prints or serialises `code` is unchanged.
#[test]
fn a_code_displays_and_compares_as_its_text() {
    for code in Code::all() {
        assert_eq!(code.to_string(), code.as_str());
        assert_eq!(format!("{code:?}"), format!("{:?}", code.as_str()));
        assert!(code == code.as_str(), "{code}");
    }
    let distinct: BTreeSet<Code> = Code::all().collect();
    assert_eq!(distinct.len(), CODES.len());
}

/// Codes order by their text, as findings sort by code text.
#[test]
fn codes_order_by_their_text() {
    let mut by_code: Vec<Code> = Code::all().collect();
    by_code.sort();
    let mut by_text: Vec<&str> = CODES.iter().map(|(c, _)| *c).collect();
    by_text.sort_unstable();
    let sorted: Vec<&str> = by_code.iter().map(|c| c.as_str()).collect();
    assert_eq!(sorted, by_text);
}

/// Every finding every emitter gives carries a catalogued code, and the
/// severity the catalogue gives that code: document findings (an error and
/// the V10 warning), every rule of a run, and every body warning.
#[test]
fn every_emitted_finding_has_a_catalogued_code_and_its_severity() {
    let task = |extra: &str| {
        format!(
            "```yaml\n.dag: issue-dag/2\n.id: o/r#1\n.kind: task\n.type: feature\n\
             .blocked_by: []\n{extra}```\n"
        )
    };
    let mut emitted: Vec<Finding> = Vec::new();
    emitted.extend(findings(&task(".size_hours: 9\n"), &subject()));
    emitted.extend(findings(&task(".status: nope\n"), &subject()));
    emitted.extend(body_warnings(&task(""), &subject(), Some("A and B")));
    emitted.extend(
        LABELS
            .iter()
            .map(|&l| Rule::Document(l))
            .chain(PROFILE_RULES)
            .map(|rule| Finding::new(subject(), rule, None)),
    );
    let severities: Vec<Severity> = emitted.iter().map(|f| f.severity).collect();
    assert!(severities.contains(&Severity::Warning));
    assert!(severities.contains(&Severity::Error));
    let catalogued: BTreeSet<&str> = CODES.iter().map(|(c, _)| *c).collect();
    for finding in &emitted {
        assert!(
            catalogued.contains(finding.code.as_str()),
            "{}",
            finding.code
        );
        assert_eq!(
            finding.severity,
            finding.code.severity(),
            "{}",
            finding.code
        );
    }
    let body: BTreeSet<&str> = emitted
        .iter()
        .map(|f| f.code.as_str())
        .filter(|c| c.starts_with("taskalisk."))
        .collect();
    let expected: BTreeSet<&str> = BODY_WARNINGS
        .iter()
        .map(|w| w.code())
        .filter(|c| !["taskalisk.outcome-items", "taskalisk.outcome-sentences"].contains(c))
        .collect();
    assert_eq!(body, expected);
}

/// A rule's code and a body warning's code are the catalogue's codes.
#[test]
fn rules_and_body_warnings_name_catalogued_codes() {
    for rule in LABELS
        .iter()
        .map(|&l| Rule::Document(l))
        .chain(PROFILE_RULES)
    {
        let finding = Finding::new(subject(), rule, None);
        assert!(finding.code == rule.code(), "{rule}");
        assert_eq!(finding.code.severity(), rule.severity(), "{rule}");
    }
    for warning in BODY_WARNINGS {
        let code = Code::all()
            .find(|c| *c == warning.code())
            .unwrap_or_else(|| panic!("{} is not catalogued", warning.code()));
        assert_eq!(code.severity(), Severity::Warning);
    }
}
