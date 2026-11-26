//! The finding reference (flyingrobots/taskalisk#60):
//! `docs/topics/findings/README.md` has one entry per finding code, in the
//! order of the catalogue [`CODES`], and no entry for a code that does not
//! exist.
//!
//! The codes are enumerated from [`CODES`], the one public catalogue of every
//! family of findings (document codes, the planning profile's codes and
//! Taskalisk's body and plan warnings), so a code that is added to the catalogue fails
//! here until its entry is written. An entry is a heading `` ### `<code>` ``
//! followed by a line `**Severity:** <severity>. **Rule:** [<label>](<link>)...`.
//! Its severity must equal the one the catalogue gives it. Every link of the
//! page, and the anchor it names, must resolve.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use issue_dag_core::{CODES, PLAN_WARNINGS};

/// The reference page, relative to the crate.
const PAGE: &str = "../../docs/topics/findings/README.md";

/// One entry of the reference: its code, severity, the text of its rule and
/// the lines that follow, up to the next heading.
#[derive(Debug, PartialEq, Eq)]
struct Entry {
    code: String,
    severity: String,
    rule: String,
    body: Vec<String>,
}

fn crate_path(relative: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join(relative)
}

fn read(path: &Path) -> String {
    fs::read_to_string(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// The entries of a reference page, in the order they are written.
fn entries_of(page: &str) -> Vec<Entry> {
    let mut found = Vec::new();
    let mut lines = page.lines().peekable();
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
        let mut body = Vec::new();
        while let Some(next) = lines.next_if(|l| !l.starts_with("## ") && !l.starts_with("### ")) {
            body.push(next.to_owned());
        }
        found.push(Entry {
            code: code.to_owned(),
            severity: severity.to_owned(),
            rule: rule.to_owned(),
            body,
        });
    }
    found
}

fn entries() -> Vec<Entry> {
    entries_of(&read(&crate_path(PAGE)))
}

/// The catalogue's codes that have no entry, and the entries that name no
/// code of the catalogue.
fn coverage<'a>(documented: &'a [String], catalogue: &'a [String]) -> (Vec<&'a str>, Vec<&'a str>) {
    let missing = catalogue
        .iter()
        .filter(|c| !documented.contains(c))
        .map(String::as_str)
        .collect();
    let unknown = documented
        .iter()
        .filter(|c| !catalogue.contains(c))
        .map(String::as_str)
        .collect();
    (missing, unknown)
}

fn catalogue() -> Vec<String> {
    CODES.iter().map(|(c, _)| (*c).to_owned()).collect()
}

#[test]
fn every_code_has_one_entry_in_catalogue_order() {
    let documented: Vec<String> = entries().into_iter().map(|e| e.code).collect();
    let catalogue = catalogue();
    let (missing, unknown) = coverage(&documented, &catalogue);
    assert!(missing.is_empty(), "codes without an entry: {missing:?}");
    assert!(unknown.is_empty(), "entries for no code: {unknown:?}");
    assert_eq!(documented, catalogue, "one entry per code, in CODES order");
}

/// The check above fails for a page that lacks the entry of a code.
#[test]
fn a_code_without_an_entry_is_reported() {
    let catalogue = catalogue();
    let documented: Vec<String> = catalogue
        .iter()
        .filter(|c| c.as_str() != "taskalisk.title-joins")
        .cloned()
        .collect();
    let (missing, unknown) = coverage(&documented, &catalogue);
    assert_eq!(missing, ["taskalisk.title-joins"]);
    assert!(unknown.is_empty(), "entries for no code: {unknown:?}");
}

/// The check above fails for a page with an entry for a code that does not
/// exist.
#[test]
fn an_entry_for_no_code_is_reported() {
    let catalogue = catalogue();
    let mut documented = catalogue.clone();
    documented.push("profile.Z9".to_owned());
    let (missing, unknown) = coverage(&documented, &catalogue);
    assert!(missing.is_empty(), "codes without an entry: {missing:?}");
    assert_eq!(unknown, ["profile.Z9"]);
}

#[test]
fn every_entry_states_its_code_s_severity_and_cites_its_rule() {
    let severities: BTreeMap<&str, &str> = CODES.iter().map(|(c, s)| (*c, s.as_str())).collect();
    for entry in entries() {
        let Some(severity) = severities.get(entry.code.as_str()) else {
            continue; // Reported by the coverage test.
        };
        assert_eq!(
            entry.severity, *severity,
            "{}: the severity differs from the catalogue",
            entry.code
        );
        let (prefix, label) = entry.code.split_once('.').expect("a prefixed code");
        if PLAN_WARNINGS.contains(&entry.code.as_str()) {
            // Taskalisk's doctrine on graph health, not a rule of a
            // specification.
            assert!(
                entry.rule.starts_with('[')
                    && entry.rule.contains("](../../../skills/taskalisk/SKILL.md#"),
                "{}: the rule {:?} does not cite SKILL.md",
                entry.code,
                entry.rule
            );
        } else if prefix == "taskalisk" {
            // Taskalisk's convention, not a rule of a specification.
            assert!(
                entry.rule.starts_with('[')
                    && entry
                        .rule
                        .contains("](../../../skills/taskalisk/WRITING-TASKS.md#"),
                "{}: the rule {:?} does not cite WRITING-TASKS.md",
                entry.code,
                entry.rule
            );
        } else {
            assert!(
                entry.rule.starts_with(&format!("[{label}](")),
                "{}: the rule {:?} does not cite label {label}",
                entry.code,
                entry.rule
            );
        }
    }
}

/// `version.P3` covers two cases that are fixed differently: a retired
/// version (`issue-dag/1`), which is migrated, and an unknown one (such as
/// `issue-dag/3`), which this reader cannot judge.
#[test]
fn p3_advises_a_retired_and_an_unknown_version_separately() {
    let p3 = entries()
        .into_iter()
        .find(|e| e.code == "version.P3")
        .expect("an entry for version.P3");
    let advice = |prefix: &str| -> String {
        let start = p3
            .body
            .iter()
            .position(|l| l.starts_with(prefix))
            .unwrap_or_else(|| panic!("version.P3: no paragraph starting {prefix:?}"));
        p3.body[start..]
            .iter()
            .take_while(|l| !l.trim().is_empty())
            .cloned()
            .collect::<Vec<_>>()
            .join(" ")
    };
    let retired = advice("To fix a retired version");
    let unknown = advice("To fix an unknown version");
    assert!(retired.contains("`issue-dag/1`"), "{retired}");
    assert!(retired.contains("`.dag: issue-dag/2`"), "{retired}");
    assert!(unknown.contains("`issue-dag/3`"), "{unknown}");
    assert_ne!(retired, unknown);
}

/// GitHub's anchor of a heading: lower case, with every character other than
/// a letter, a digit, a space, `-` or `_` dropped, and each space a `-`.
fn slug(heading: &str) -> String {
    heading
        .trim()
        .to_lowercase()
        .chars()
        .filter(|c| c.is_alphanumeric() || matches!(c, ' ' | '-' | '_'))
        .map(|c| if c == ' ' { '-' } else { c })
        .collect()
}

/// The anchors of a Markdown page: one per heading outside a fenced code
/// block, a repeated one suffixed `-1`, `-2` and so on.
fn anchors(page: &str) -> Vec<String> {
    let mut found: Vec<String> = Vec::new();
    let mut seen: BTreeMap<String, usize> = BTreeMap::new();
    let mut fenced = false;
    for line in page.lines() {
        if line.trim_start().starts_with("```") {
            fenced = !fenced;
            continue;
        }
        if fenced {
            continue;
        }
        let Some(text) = line
            .strip_prefix('#')
            .map(|t| t.trim_start_matches('#'))
            .and_then(|t| t.strip_prefix(' '))
        else {
            continue;
        };
        let base = slug(text);
        let count = seen.entry(base.clone()).or_insert(0);
        found.push(if *count == 0 {
            base
        } else {
            format!("{base}-{count}")
        });
        *count += 1;
    }
    found
}

/// The link targets of a Markdown page outside fenced code blocks: the text
/// between `](` and the next `)`.
fn links(page: &str) -> Vec<String> {
    let mut found = Vec::new();
    let mut fenced = false;
    for line in page.lines() {
        if line.trim_start().starts_with("```") {
            fenced = !fenced;
            continue;
        }
        if fenced {
            continue;
        }
        let mut rest = line;
        while let Some(start) = rest.find("](") {
            let after = &rest[start + 2..];
            let end = after
                .find(')')
                .unwrap_or_else(|| panic!("an unclosed link in {line:?}"));
            found.push(after[..end].to_owned());
            rest = &after[end..];
        }
    }
    found
}

/// The links of `page`, which lives in `dir`, whose file or anchor does not
/// resolve. A link to another site is not followed.
fn broken_links(page: &str, dir: &Path) -> Vec<String> {
    let mut broken = Vec::new();
    for target in links(page) {
        if target.starts_with("http://") || target.starts_with("https://") {
            continue;
        }
        let (file, anchor) = match target.split_once('#') {
            Some((file, anchor)) => (file, Some(anchor)),
            None => (target.as_str(), None),
        };
        let text = if file.is_empty() {
            page.to_owned()
        } else {
            let path = dir.join(file);
            let Ok(text) = fs::read_to_string(&path).or_else(|e| {
                if path.is_dir() {
                    Ok(String::new())
                } else {
                    Err(e)
                }
            }) else {
                broken.push(format!("{target}: no such file"));
                continue;
            };
            text
        };
        if let Some(anchor) = anchor
            && !anchors(&text).iter().any(|a| a == anchor)
        {
            broken.push(format!("{target}: no such anchor"));
        }
    }
    broken
}

#[test]
fn every_link_and_anchor_in_the_reference_resolves() {
    let path = crate_path(PAGE);
    let dir = path.parent().expect("the page's directory");
    let broken = broken_links(&read(&path), dir);
    assert!(broken.is_empty(), "broken links: {broken:?}");
}

/// The link check reports a missing file, a missing anchor in another page
/// and a missing anchor in the page itself, and passes the ones that exist.
#[test]
fn a_broken_link_or_anchor_is_reported() {
    let path = crate_path(PAGE);
    let dir = path.parent().expect("the page's directory");
    let page = "# Title\n\n## A section\n\n\
        [ok](#a-section) [ok](../output/README.md) [ok](../output/README.md#finding-codes)\n\
        [file](no-such-page.md) [anchor](../output/README.md#no-such-anchor) [own](#nowhere)\n\
        ```\n[fenced](not-a-link.md)\n```\n";
    assert_eq!(
        broken_links(page, dir),
        [
            "no-such-page.md: no such file",
            "../output/README.md#no-such-anchor: no such anchor",
            "#nowhere: no such anchor",
        ]
    );
}

#[test]
fn a_heading_s_anchor_is_github_s() {
    assert_eq!(slug("2. Carrier"), "2-carrier");
    assert_eq!(slug("`format.C4`"), "formatc4");
    assert_eq!(slug("4. Values of format keys"), "4-values-of-format-keys");
    assert_eq!(
        anchors("# A\n## B\n## B\n```\n# C\n```\n"),
        ["a", "b", "b-1"]
    );
}
