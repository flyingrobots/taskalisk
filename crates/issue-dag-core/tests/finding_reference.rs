//! The finding reference (flyingrobots/taskalisk#60):
//! `docs/topics/findings/README.md` has one entry per finding code, in the
//! order of [`LABELS`], and no entry for a code that does not exist.
//!
//! The codes are enumerated from [`LABELS`] through [`code`], so a code that
//! is added to the catalogue fails here until its entry is written. An entry
//! is a heading `` ### `<code>` `` followed by a line
//! `**Severity:** <severity>. **Rule:** [<label>](<link>)...`. Its severity must equal
//! the one the crate's code table (on `code`, in `src/finding.rs`) gives it.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use issue_dag_core::{LABELS, code};

/// One entry of the reference: its code, severity and the text of its rule.
#[derive(Debug, PartialEq, Eq)]
struct Entry {
    code: String,
    severity: String,
    rule: String,
}

fn read(relative: &str) -> String {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join(relative);
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// The entries of the reference page, in the order they are written.
fn entries() -> Vec<Entry> {
    let page = read("../../docs/topics/findings/README.md");
    let mut found = Vec::new();
    let mut lines = page.lines();
    while let Some(line) = lines.next() {
        let Some(heading) = line.strip_prefix("### `") else {
            continue;
        };
        let code = heading
            .strip_suffix('`')
            .unwrap_or_else(|| panic!("entry heading {line:?} is not ### `<code>`"));
        let facts = lines
            .by_ref()
            .find(|l| !l.trim().is_empty())
            .unwrap_or_else(|| panic!("{code}: no line after the heading"));
        let (severity, rule) = facts
            .strip_prefix("**Severity:** ")
            .and_then(|rest| rest.split_once(". **Rule:** "))
            .unwrap_or_else(|| {
                panic!("{code}: {facts:?} is not **Severity:** <severity>. **Rule:** ...")
            });
        found.push(Entry {
            code: code.to_owned(),
            severity: severity.to_owned(),
            rule: rule.to_owned(),
        });
    }
    found
}

/// The severity of each code, from the code table on `code`.
fn table_severities() -> BTreeMap<String, String> {
    read("src/finding.rs")
        .lines()
        .filter_map(|l| l.trim_start().strip_prefix("/// | `"))
        .map(|row| {
            let cells: Vec<&str> = row.split('|').map(str::trim).collect();
            (
                cells[0].trim_end_matches('`').to_owned(),
                cells[2].to_owned(),
            )
        })
        .collect()
}

#[test]
fn every_code_has_one_entry_in_catalogue_order() {
    let documented: Vec<String> = entries().into_iter().map(|e| e.code).collect();
    let catalogue: Vec<String> = LABELS.iter().map(|l| code(*l).to_owned()).collect();
    let missing: Vec<&String> = catalogue
        .iter()
        .filter(|c| !documented.contains(c))
        .collect();
    let unknown: Vec<&String> = documented
        .iter()
        .filter(|c| !catalogue.contains(c))
        .collect();
    assert!(missing.is_empty(), "codes without an entry: {missing:?}");
    assert!(unknown.is_empty(), "entries for no code: {unknown:?}");
    assert_eq!(documented, catalogue, "one entry per code, in LABELS order");
}

#[test]
fn every_entry_states_its_code_s_severity_and_cites_its_label() {
    let severities = table_severities();
    let labels: BTreeMap<&str, &str> = LABELS.iter().map(|l| (code(*l), l.as_str())).collect();
    for entry in entries() {
        let Some(label) = labels.get(entry.code.as_str()) else {
            continue; // Reported by the test above.
        };
        assert_eq!(
            Some(&entry.severity),
            severities.get(&entry.code),
            "{}: the severity differs from the code table",
            entry.code
        );
        assert!(
            entry.rule.starts_with(&format!("[{label}](")),
            "{}: the rule {:?} does not cite label {label}",
            entry.code,
            entry.rule
        );
    }
}
