//! The views of a plan (flyingrobots/taskalisk#68).
//!
//! The ROADMAP block and the Mermaid flowchart against the Python's
//! `--emit-roadmap` and `--emit-mermaid`, on every fixture of the parity
//! test: `tests/fixtures/render/views/python/<case>.roadmap.md` and
//! `<case>.mermaid.mmd` hold the `text` of the Python's `taskalisk.rendering`
//! line (captured by `tests/capture_render_parity.py`), and the Rust view,
//! given the display input read from the Python's lines, equals it but for:
//!
//! - the artifact hash the block names, which is the Rust one where the
//!   result document holds an intended difference or a gap ([`hash_differs`]);
//! - [`INTENDED_DIFFERENCE`]: a Mermaid label also drops control and
//!   bidirectional characters and turns `{` and `}` into `(` and `)`.
//!
//! A view exists exactly when the Python renders one: only for a plan that
//! is `ok`.
//!
//! The status-coloured flowchart is Rust's alone, so it is held by golden
//! files, `tests/fixtures/render/views/rust/<case>.status.mmd`
//! (`TASKALISK_BLESS=1` rewrites them), and by the assertions below on the
//! fixture with a node in each state and on the one with hostile titles.

mod common;

use std::collections::{BTreeMap, BTreeSet};
use std::fs;

use common::{cases, display_of, fixtures, hash_differs, planned, python};
use taskalisk::render::{Display, lines};
use taskalisk::views::{LEGEND, View, view};

fn rendered(case: &str, display: Option<&Display>, which: View) -> Option<String> {
    let (parameters, outcome) = planned(case).unwrap_or_else(|e| panic!("{case}: {e}"));
    view(&parameters, &outcome, display, which).unwrap_or_else(|e| panic!("{case}: {e:?}"))
}

/// The Rust plan line's `artifact_hash`.
fn rust_hash(case: &str, display: &Display) -> String {
    let (parameters, outcome) = planned(case).expect("planned");
    let lines = lines(&parameters, &outcome, Some(display)).expect("rendered");
    lines[0]["artifact_hash"]
        .as_str()
        .expect("a hash")
        .to_owned()
}

/// What a Mermaid label also drops: the C0 and C1 controls and the
/// bidirectional controls, as a Markdown cell does (threat model C5).
fn dropped(c: char) -> bool {
    matches!(c, '\0'..='\x1f' | '\x7f'..='\u{9f}' | '\u{61c}' | '\u{200e}' | '\u{200f}' | '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
}

/// The intended difference, applied to a line of the Python's flowchart:
/// a label drops what [`dropped`] names and turns braces into parentheses,
/// so that no title can open a Mermaid directive (`%%{init: ...}%%`), which
/// Mermaid reads anywhere in the text, inside a quoted label too.
const INTENDED_DIFFERENCE: &str = "Mermaid labels drop controls and turn braces into parentheses";

fn intended(line: &str) -> String {
    line.chars()
        .filter(|&c| !dropped(c))
        .map(|c| match c {
            '{' => '(',
            '}' => ')',
            c => c,
        })
        .collect()
}

/// The Python's view as Rust writes it: the intended difference on every
/// line of a flowchart (the whole Mermaid view, or the ROADMAP block's
/// `mermaid` fence), and the Rust hash where the two differ.
fn expected(python: &str, mermaid: bool, hash: Option<(&str, &str)>) -> String {
    let mut fenced = mermaid;
    let mut out: Vec<String> = Vec::new();
    for line in python.split('\n') {
        if !mermaid && line == "```" {
            fenced = false;
        }
        out.push(if fenced {
            intended(line)
        } else {
            line.to_owned()
        });
        if !mermaid && line == "```mermaid" {
            fenced = true;
        }
    }
    let text = out.join("\n");
    match hash {
        Some((theirs, ours)) => text.replace(
            &format!("Artifact hash `{theirs}`"),
            &format!("Artifact hash `{ours}`"),
        ),
        None => text,
    }
}

/// The 16 hexadecimal digits the Python's ROADMAP block names.
fn named_hash(block: &str) -> String {
    let start = block.find("Artifact hash `").expect("a hash") + "Artifact hash `".len();
    block[start..start + 16].to_owned()
}

#[test]
fn every_view_renders_as_the_python_does() {
    let mut failures = Vec::new();
    let mut compared = 0;
    let mut differed: BTreeSet<String> = BTreeSet::new();
    for case in cases() {
        let python = python(&case);
        let display = display_of(&python);
        let hash = rust_hash(&case, &display);
        for (which, suffix, mermaid) in [
            (View::Roadmap, ".roadmap.md", false),
            (View::Mermaid, ".mermaid.mmd", true),
        ] {
            let name = format!("{case}{suffix}");
            let want = fs::read_to_string(fixtures().join("views/python").join(&name)).ok();
            let got = rendered(&case, Some(&display), which);
            if rendered(&case, Some(&display), which) != got {
                failures.push(format!("{name}: two renderings differ"));
            }
            match (want, got) {
                (None, None) => {}
                (Some(want), Some(got)) => {
                    compared += 1;
                    let theirs = (!mermaid).then(|| named_hash(&want));
                    if let Some(theirs) = &theirs
                        && !hash_differs(&python)
                        && theirs != &hash[..16]
                    {
                        failures.push(format!("{name}: the Python's hash {theirs}, Rust's {hash}"));
                    }
                    let swap = theirs
                        .as_deref()
                        .filter(|_| hash_differs(&python))
                        .map(|t| (t, &hash[..16]));
                    let unchanged = expected(&want, mermaid, None);
                    if unchanged != want {
                        differed.insert(name.clone());
                    }
                    let want = expected(&want, mermaid, swap);
                    if want != got {
                        failures.push(format!("{name}:\n--- python\n{want}\n--- rust\n{got}"));
                    }
                }
                (want, got) => failures.push(format!(
                    "{name}: the Python renders {}, Rust {}",
                    if want.is_some() { "it" } else { "nothing" },
                    if got.is_some() { "it" } else { "nothing" },
                )),
            }
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
    assert!(compared > 250, "too few views: {compared}");
    // The intended difference shows only where a title holds what it drops
    // or turns: the two fixtures with hostile titles.
    let titled: BTreeSet<String> = [
        "discovery-unmodeled-home-issue--titles",
        "golden-plan-rich--every-status--titles",
    ]
    .iter()
    .flat_map(|c| [format!("{c}.roadmap.md"), format!("{c}.mermaid.mmd")])
    .collect();
    assert_eq!(differed, titled, "{INTENDED_DIFFERENCE}");
}

#[test]
fn a_view_without_a_display_input_has_no_titles_and_no_links() {
    let case = "golden-plan-rich--every-status";
    let block = rendered(case, None, View::Roadmap).expect("a block");
    assert!(!block.contains("](http"), "{block}");
    assert!(!block.contains("(title not recorded)"), "{block}");
    let diagram = rendered(case, None, View::StatusMermaid).expect("a diagram");
    assert!(
        diagram.contains(r#"["flyingrobots/geordi#1:"]:::review"#),
        "{diagram}"
    );
}

/// Every status-coloured diagram, held byte for byte.
#[test]
fn every_status_diagram_is_its_golden_file() {
    let bless = std::env::var_os("TASKALISK_BLESS").is_some();
    let dir = fixtures().join("views/rust");
    let mut failures = Vec::new();
    let mut want_files = BTreeSet::new();
    for case in cases() {
        let display = display_of(&python(&case));
        let Some(got) = rendered(&case, Some(&display), View::StatusMermaid) else {
            continue;
        };
        let name = format!("{case}.status.mmd");
        let path = dir.join(&name);
        want_files.insert(name.clone());
        if bless {
            fs::create_dir_all(&dir).expect("mkdir");
            fs::write(&path, &got).expect("write the golden file");
        } else if fs::read_to_string(&path).ok().as_deref() != Some(got.as_str()) {
            failures.push(format!(
                "{name} differs (TASKALISK_BLESS=1 rewrites it):\n{got}"
            ));
        }
    }
    let on_disk: BTreeSet<String> = fs::read_dir(&dir)
        .map(|entries| {
            entries
                .map(|e| e.expect("entry").file_name().into_string().expect("UTF-8"))
                .collect()
        })
        .unwrap_or_default();
    assert!(failures.is_empty(), "{}", failures.join("\n"));
    assert_eq!(
        on_disk, want_files,
        "a golden file without a diagram, or none"
    );
    assert!(
        want_files.len() > 100,
        "too few diagrams: {}",
        want_files.len()
    );
}

/// The node lines of a diagram: `key["label"]:::class`, by the label's id.
fn classes(diagram: &str) -> BTreeMap<String, String> {
    diagram
        .lines()
        .filter_map(|l| {
            let (node, class) = l.trim().rsplit_once("\"]:::")?;
            let label = node.split_once("[\"")?.1;
            let id = label.split(':').next()?.to_owned();
            Some((id, class.to_owned()))
        })
        .collect()
}

#[test]
fn each_state_gets_its_class() {
    let case = "golden-plan-rich--every-status";
    let display = display_of(&python(case));
    let diagram = rendered(case, Some(&display), View::StatusMermaid).expect("a diagram");
    let want: BTreeMap<String, String> = [
        // A ready pull request: in review, though it waits on echo#5.
        ("flyingrobots/geordi#1", "review"),
        // A draft pull request: active.
        ("flyingrobots/geordi#3", "active"),
        // Wave 0, open, nothing claims it.
        ("flyingrobots/echo#5", "open"),
        // `.status: blocked` in Wave 0, and the open nodes that wait.
        ("flyingrobots/bunny#110", "blocked"),
        ("flyingrobots/echo#6", "blocked"),
        ("flyingrobots/geordi#110", "blocked"),
        ("flyingrobots/geordi#2", "blocked"),
        // Parked and waiting: blocked.
        ("flyingrobots/geordi#4", "blocked"),
        // The completed prerequisites.
        ("flyingrobots/bunny#7", "done"),
        ("flyingrobots/echo#99", "done"),
    ]
    .iter()
    .map(|&(id, class)| (id.to_owned(), class.to_owned()))
    .collect();
    assert_eq!(classes(&diagram), want, "{diagram}");

    // `.status: active` is active too; a parked node in Wave 0 is open.
    let case = "s2-status-values";
    let display = display_of(&python(case));
    let diagram = rendered(case, Some(&display), View::StatusMermaid).expect("a diagram");
    let got = classes(&diagram);
    assert_eq!(got["o/r#1"], "active", "{diagram}");
    assert_eq!(got["o/r#2"], "open", "{diagram}");
    assert_eq!(got["o/r#3"], "blocked", "{diagram}");
    assert_eq!(got["o/r#4"], "open", "{diagram}");
}

#[test]
fn done_prerequisites_are_dashed_nodes_with_dotted_edges() {
    let case = "golden-plan-rich--every-status";
    let display = display_of(&python(case));
    let diagram = rendered(case, Some(&display), View::StatusMermaid).expect("a diagram");
    let key = |id: &str| {
        diagram
            .lines()
            .find(|l| l.contains(&format!("[\"{id}:")))
            .and_then(|l| l.trim().split_once("[\""))
            .map(|(k, _)| k.to_owned())
            .unwrap_or_else(|| panic!("no node {id}:\n{diagram}"))
    };
    for (done, open) in [
        ("flyingrobots/bunny#7", "flyingrobots/echo#5"),
        ("flyingrobots/echo#99", "flyingrobots/geordi#1"),
    ] {
        let edge = format!("  {} -.-> {}", key(done), key(open));
        assert!(diagram.lines().any(|l| l == edge), "no {edge}:\n{diagram}");
    }
    // Every edge from a done node is dotted, and every other edge solid.
    let dotted = diagram.lines().filter(|l| l.contains(" -.-> ")).count();
    assert_eq!(dotted, 2, "{diagram}");
    let done_def = diagram
        .lines()
        .find(|l| l.trim_start().starts_with("classDef done "))
        .expect("classDef done");
    assert!(done_def.contains("stroke-dasharray"), "{done_def}");
    let defs: Vec<&str> = diagram
        .lines()
        .filter_map(|l| l.trim_start().strip_prefix("classDef "))
        .filter_map(|l| l.split(' ').next())
        .collect();
    assert_eq!(defs, ["done", "blocked", "open", "active", "review"]);
}

#[test]
fn the_legend_names_each_state_and_its_colour() {
    assert!(!LEGEND.contains('\n'), "one line: {LEGEND}");
    for words in [
        "light dashed = done",
        "grey = blocked",
        "green = open and unclaimed",
        "blue = active (draft pull request)",
        "purple = in review",
    ] {
        assert!(LEGEND.contains(words), "{words}: {LEGEND}");
    }
}

/// Characters no label may hold: they could end the label, start a tag,
/// open a directive or hide text (threat model T08, C5).
fn unsafe_in_label(c: char) -> bool {
    matches!(c, '"' | '<' | '>' | '[' | ']' | '{' | '}')
        || dropped(c)
        || c.is_whitespace() && c != ' '
}

#[test]
fn hostile_titles_stay_inside_their_labels() {
    let case = "golden-plan-rich--every-status--titles";
    let display = display_of(&python(case));
    assert!(
        display.titles.values().any(|t| t.contains("<script>")),
        "the fixture holds its hostile titles"
    );
    for which in [View::Mermaid, View::StatusMermaid] {
        let diagram = rendered(case, Some(&display), which).expect("a diagram");
        let bare = rendered(case, None, which).expect("a diagram");
        // The same shape as without titles: no line added or removed.
        assert_eq!(diagram.lines().count(), bare.lines().count(), "{diagram}");
        for (line, shape) in diagram.lines().zip(bare.lines()) {
            let Some((key, rest)) = line.split_once("[\"") else {
                assert_eq!(line, shape);
                continue;
            };
            assert_eq!(Some(key), shape.split_once("[\"").map(|(k, _)| k), "{line}");
            let (label, tail) = rest.rsplit_once("\"]").expect("a closed label");
            assert_eq!(
                Some(tail),
                shape.rsplit_once("\"]").map(|(_, t)| t),
                "{line}"
            );
            assert!(
                !label.chars().any(unsafe_in_label),
                "{which:?}: an unsafe character in {label:?}"
            );
            // The id, `: `, and at most 48 characters of title.
            let title = label.split_once(": ").map_or("", |(_, t)| t);
            assert!(title.chars().count() <= 48, "{label}");
        }
        for directive in ["%%{", "<script", "-->  N_evil", ":::open --> N_evil"] {
            assert!(!diagram.contains(directive), "{directive} in:\n{diagram}");
        }
    }
}
