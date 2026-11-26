//! Views of a plan: the ROADMAP block, the Mermaid flowchart, and the
//! status-coloured Mermaid flowchart with its legend
//! (flyingrobots/taskalisk#68).
//!
//! Each is rendered from the result document [`crate::render`] emits, in
//! the 1.x shape, as the Python renders `--emit-roadmap` and
//! `--emit-mermaid` from its result. A view exists only for a plan that is
//! `ok`, as the `taskalisk.rendering` line does. Nothing here reads or
//! writes anything.
//!
//! The ROADMAP block and the plain flowchart are the Python's, byte for
//! byte, with one intended difference (threat model C5): a Mermaid label
//! also drops control and bidirectional characters, and turns `{` and `}`
//! into `(` and `)`, so no title can open a Mermaid directive
//! (`%%{init: ...}%%`), which Mermaid reads anywhere in the text, a quoted
//! label included. The status-coloured flowchart is new: it exists only
//! here.
//!
//! # Escaping (threat model T08, C5)
//!
//! Titles are display text from GitHub. A Mermaid label is
//! `"<id>: <title>"`: the title is cut to 48 characters, every run of
//! whitespace (line breaks included) becomes one space, `"` becomes `'`,
//! `<`, `>`, `[`, `]`, `{`, `}` become parentheses, and control and
//! bidirectional characters are dropped. The label starts with the id, so
//! it is never a Markdown string. A Markdown cell of the ROADMAP block is
//! escaped as C5 states (see [`md_cell`]); a resource key is a code span
//! (see [`md_code`]). An untrusted issue's title is never rendered (C3).

use std::collections::BTreeMap;
use std::fmt::Write as _;

use issue_dag_core::{Outcome, Parameters};
use serde_json::Value;

use crate::render::{Display, NotRendered, result_document};

/// A view of a plan.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum View {
    /// The ROADMAP block between [`ROADMAP_BEGIN`] and [`ROADMAP_END`]
    /// (`--emit-roadmap`), the Python's.
    Roadmap,
    /// The Mermaid flowchart of the reduced graph by wave, uncoloured: the
    /// Python's `--emit-mermaid`, and the one the ROADMAP block holds.
    Mermaid,
    /// The Mermaid flowchart with each node coloured by its state, the
    /// completed prerequisites as dashed nodes with dotted edges; post it
    /// with [`LEGEND`].
    StatusMermaid,
}

impl View {
    /// The `format` of the `taskalisk.rendering` line that carries it.
    #[must_use]
    pub const fn format(self) -> &'static str {
        match self {
            Self::Roadmap => "roadmap",
            Self::Mermaid | Self::StatusMermaid => "mermaid",
        }
    }
}

/// The first line of the ROADMAP block.
pub const ROADMAP_BEGIN: &str =
    "<!-- BEGIN GENERATED ISSUE DAG (taskalisk --emit-roadmap; do not edit by hand) -->";
/// The last line of the ROADMAP block.
pub const ROADMAP_END: &str = "<!-- END GENERATED ISSUE DAG -->";

/// The legend of [`View::StatusMermaid`]: one Markdown line to post with
/// the diagram.
pub const LEGEND: &str = "**Legend:** light dashed = done, grey = blocked, \
     green = open and unclaimed, blue = active (draft pull request), purple = in review.";

/// The longest title a Mermaid label shows; a longer one is cut to 45
/// characters and `...`.
const MERMAID_TITLE_MAX: usize = 48;

/// The class of each state, in the order they are defined. The fills are
/// light and the text dark, so a node reads on GitHub's light and dark
/// themes alike (a `classDef` does not follow the theme); the strokes are
/// mid-tones, which show on both backgrounds.
const CLASSES: [(&str, &str); 5] = [
    (
        "done",
        "fill:#f6f8fa,stroke:#8c959f,stroke-width:1px,stroke-dasharray:4 3,color:#57606a",
    ),
    (
        "blocked",
        "fill:#d0d7de,stroke:#6e7781,stroke-width:2px,color:#1f2328",
    ),
    (
        "open",
        "fill:#aceebb,stroke:#1a7f37,stroke-width:2px,color:#0f2e17",
    ),
    (
        "active",
        "fill:#b6e3ff,stroke:#0969da,stroke-width:2px,color:#0a2540",
    ),
    (
        "review",
        "fill:#e2d4ff,stroke:#8250df,stroke-width:2px,color:#2e1065",
    ),
];

/// A view of a plan: `None` when the plan is not `ok`, which has no view.
///
/// # Errors
///
/// [`NotRendered`] when the run has no plan to render.
pub fn view(
    parameters: &Parameters,
    outcome: &Outcome,
    display: Option<&Display>,
    which: View,
) -> Result<Option<String>, NotRendered> {
    let document = result_document(parameters, outcome, display)?;
    if document["ok"] != Value::Bool(true) {
        return Ok(None);
    }
    Ok(Some(match which {
        View::Roadmap => roadmap_block(&document),
        View::Mermaid => flowchart(&document),
        View::StatusMermaid => status_flowchart(&document),
    }))
}

fn str_of(value: &Value) -> &str {
    value.as_str().unwrap_or_default()
}

fn list(value: &Value) -> &[Value] {
    value.as_array().map_or(&[], Vec::as_slice)
}

/// A JSON scalar as Python's `str` writes it in an f-string (numbers as
/// JSON writes them, which for these values is the same).
fn scalar(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

fn joined(items: &[Value], separator: &str) -> String {
    items.iter().map(str_of).collect::<Vec<_>>().join(separator)
}

/// The waves in order: `Wave 0`, `Wave 1`, ... (the document's map is
/// sorted by name, which puts `Wave 10` before `Wave 2`).
fn waves(document: &Value) -> Vec<(String, &[Value])> {
    let mut out = Vec::new();
    for k in 0.. {
        let name = format!("Wave {k}");
        match document["waves"].get(&name) {
            Some(items) => out.push((name, list(items))),
            None => break,
        }
    }
    out
}

/// The node's title, or nothing without a display input.
fn title(node: &Value) -> &str {
    str_of(&node["title"])
}

/// Whether Python's `str.isspace` holds: Unicode's white space and the
/// information separators U+001C to U+001F.
fn python_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// A C0 or C1 control or a bidirectional control (embeddings, overrides,
/// isolates, marks).
const fn control(c: char) -> bool {
    matches!(
        c,
        '\0'..='\x1f'
            | '\x7f'..='\u{9f}'
            | '\u{61c}'
            | '\u{200e}'
            | '\u{200f}'
            | '\u{202a}'..='\u{202e}'
            | '\u{2066}'..='\u{2069}'
    )
}

/// A Unicode line break, as the ROADMAP block folds them.
const fn line_break(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r' | '\x0b' | '\x0c' | '\u{85}' | '\u{2028}' | '\u{2029}'
    )
}

/// A node's label: `<id>: <title>`, made safe (see the module's
/// documentation).
fn label(id: &str, title: &str) -> String {
    let title: String = if title.chars().count() > MERMAID_TITLE_MAX {
        title
            .chars()
            .take(MERMAID_TITLE_MAX - 3)
            .chain("...".chars())
            .collect()
    } else {
        title.to_owned()
    };
    let text = format!("{id}: {title}");
    let folded = text
        .split(python_space)
        .filter(|w| !w.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    folded
        .chars()
        .filter(|&c| !control(c))
        .map(|c| match c {
            '"' => '\'',
            '<' | '[' | '{' => '(',
            '>' | ']' | '}' => ')',
            c => c,
        })
        .collect()
}

/// The Python's node key: `N_` and the id with every character but an
/// ASCII letter, digit or `_` as `_`.
fn safe_id(id: &str) -> String {
    let mut out = String::from("N_");
    out.extend(id.chars().map(|c| {
        if c.is_ascii_alphanumeric() || c == '_' {
            c
        } else {
            '_'
        }
    }));
    out
}

/// A node key of the status diagram, one per id: `N_` and the id with
/// every byte but an ASCII letter or digit as `_` and two hexadecimal
/// digits, so `a/b-c#1` and `a/b_c#1` never share one.
fn node_key(id: &str) -> String {
    let mut out = String::from("N_");
    for b in id.bytes() {
        if b.is_ascii_alphanumeric() {
            out.push(char::from(b));
        } else {
            let _ = write!(out, "_{b:02x}");
        }
    }
    out
}

fn wave_heading(name: &str) -> String {
    if name == "Wave 0" {
        format!("{name}: Open Frontier (Zero Incomplete Parents)")
    } else {
        name.to_owned()
    }
}

/// The flowchart, by wave, with each node's label from `node_line` and the
/// reduced edges after the waves.
fn flowchart_with(
    document: &Value,
    key: fn(&str) -> String,
    node_line: impl Fn(&Value, &str) -> String,
) -> (Vec<String>, Vec<String>) {
    let mut lines = vec!["flowchart TD".to_owned()];
    let mut edges = Vec::new();
    for (name, items) in waves(document) {
        let sg: String = name.chars().filter(char::is_ascii_alphanumeric).collect();
        lines.push(format!("  subgraph {sg}[\"{}\"]", wave_heading(&name)));
        for item in items {
            let id = str_of(&item["id"]);
            lines.push(node_line(item, &key(id)));
            for child in list(&item["directly_unlocks"]) {
                edges.push(format!("  {} --> {}", key(id), key(str_of(child))));
            }
        }
        lines.push("  end".to_owned());
    }
    (lines, edges)
}

/// The Python's `--emit-mermaid`.
fn flowchart(document: &Value) -> String {
    let (mut lines, edges) = flowchart_with(document, safe_id, |item, key| {
        format!("    {key}[\"{}\"]", label(str_of(&item["id"]), title(item)))
    });
    lines.extend(edges);
    lines.join("\n")
}

/// A node's class: in review, active (a draft pull request or
/// `.status: active`), blocked (it waits, or `.status: blocked`, or
/// opaque), or open (Wave 0, unclaimed; a parked node there too).
fn class(node: &Value) -> &'static str {
    match (str_of(&node["status"]), str_of(&node["derived_status"])) {
        ("in-review", _) => "review",
        ("wip" | "in-progress", _) => "active",
        ("blocked", _) | (_, "blocked") => "blocked",
        _ => "open",
    }
}

/// An id's place in the Python's `id_sort_key`: its repository, then its
/// number.
fn id_order(id: &str) -> (String, u64) {
    match id.rsplit_once('#') {
        Some((slug, n)) => (slug.to_owned(), n.parse().unwrap_or(0)),
        None => (String::new(), 0),
    }
}

/// The status-coloured flowchart: the plain one's waves and edges, each
/// node with its class, the completed prerequisites as `done` nodes with a
/// dotted edge to each node that names them, and the classes.
fn status_flowchart(document: &Value) -> String {
    let (mut lines, edges) = flowchart_with(document, node_key, |item, key| {
        format!(
            "    {key}[\"{}\"]:::{}",
            label(str_of(&item["id"]), title(item)),
            class(item)
        )
    });
    let mut done: Vec<&str> = Vec::new();
    let mut dotted = Vec::new();
    for (_, items) in waves(document) {
        for item in items {
            for parent in list(&item["completed_parents"]) {
                let parent = str_of(parent);
                if !done.contains(&parent) {
                    done.push(parent);
                }
                dotted.push(format!(
                    "  {} -.-> {}",
                    node_key(parent),
                    node_key(str_of(&item["id"]))
                ));
            }
        }
    }
    done.sort_by_cached_key(|id| id_order(id));
    for id in done {
        lines.push(format!(
            "  {}[\"{}\"]:::done",
            node_key(id),
            label(id, "done")
        ));
    }
    lines.extend(edges);
    lines.extend(dotted);
    for (name, style) in CLASSES {
        lines.push(format!("  classDef {name} {style}"));
    }
    lines.join("\n")
}

/// Whether the Python's `[a-z]` under `IGNORECASE` matches: the ASCII
/// letters and the four that fold to one (`İ`, `ı`, `ſ`, `K`).
const fn scheme_letter(c: char) -> bool {
    c.is_ascii_alphabetic() || matches!(c, '\u{130}' | '\u{131}' | '\u{17f}' | '\u{212a}')
}

/// Where GFM would start a link at `i`: the length of the text to keep
/// before a zero-width space and of the whole match, as the Python's
/// `MD_AUTOLINK_RE` matches: `scheme:` before `//`, `www` before `.`, an
/// `@` before any non-space character.
fn autolink_at(chars: &[char], i: usize) -> Option<(usize, usize)> {
    let at = |k: usize| chars.get(k).copied();
    if at(i).is_some_and(scheme_letter) {
        let mut j = i + 1;
        while j - i - 1 < 31
            && at(j).is_some_and(|c| scheme_letter(c) || c.is_ascii_digit() || "+.-".contains(c))
        {
            j += 1;
        }
        if at(j) == Some(':') && at(j + 1) == Some('/') && at(j + 2) == Some('/') {
            return Some((j + 1 - i, j + 3 - i));
        }
    }
    let www = (0..3).all(|k| at(i + k).is_some_and(|c| c.eq_ignore_ascii_case(&'w')));
    if www && at(i + 3) == Some('.') {
        return Some((3, 4));
    }
    if at(i) == Some('@') && at(i + 1).is_some_and(|c| !python_space(c)) {
        return Some((1, 1));
    }
    None
}

/// The length of the character reference GFM would decode at `&` (`&#64;`,
/// `&#x40;`, `&amp;`), as the Python's `MD_CHAR_REF_RE` reads them.
fn char_ref(chars: &[char]) -> bool {
    let run = |from: usize, ok: fn(&char) -> bool, max: usize| -> usize {
        chars[from.min(chars.len())..]
            .iter()
            .take(max + 1)
            .take_while(|c| ok(c))
            .count()
    };
    let ends = |k: usize| chars.get(k) == Some(&';');
    match chars.first() {
        Some('#') => {
            if matches!(chars.get(1), Some('x' | 'X')) {
                let n = run(2, char::is_ascii_hexdigit, 6);
                (1..=6).contains(&n) && ends(2 + n)
            } else {
                let n = run(1, char::is_ascii_digit, 7);
                (1..=7).contains(&n) && ends(1 + n)
            }
        }
        Some(c) if c.is_ascii_alphabetic() => {
            let n = run(1, char::is_ascii_alphanumeric, 31);
            (1..=31).contains(&n) && ends(1 + n)
        }
        _ => false,
    }
}

/// Line breaks folded to a space (`\r\n` to one) and controls dropped.
fn folded_text(text: &str) -> Vec<char> {
    let chars: Vec<char> = text.chars().collect();
    let mut out = Vec::with_capacity(chars.len());
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        if c == '\r' && chars.get(i + 1) == Some(&'\n') {
            out.push(' ');
            i += 2;
            continue;
        }
        if line_break(c) {
            out.push(' ');
        } else if !control(c) {
            out.push(c);
        }
        i += 1;
    }
    out
}

/// Issue text in a rendered Markdown cell (threat model C5): no pipes, no
/// HTML, no links, no line breaks, no control characters. The backslash is
/// escaped first; every line break becomes a space; every other control
/// and bidirectional character is dropped; the `&` of a character
/// reference becomes `&amp;`; `|`, `[`, `]` are escaped and `<`, `>`
/// become entities; and a zero-width space follows the colon of every
/// `scheme://`, the `www` of every `www.` and an `@` before any non-space
/// character. As the Python's `_md_cell`.
fn md_cell(text: &str) -> String {
    let chars = folded_text(&text.replace('\\', "\\\\"));
    let mut escaped: Vec<char> = Vec::with_capacity(chars.len());
    for (i, &c) in chars.iter().enumerate() {
        match c {
            '&' if char_ref(&chars[i + 1..]) => escaped.extend("&amp;".chars()),
            '|' => escaped.extend("\\|".chars()),
            '<' => escaped.extend("&lt;".chars()),
            '>' => escaped.extend("&gt;".chars()),
            '[' => escaped.extend("\\[".chars()),
            ']' => escaped.extend("\\]".chars()),
            c => escaped.push(c),
        }
    }
    let mut out = String::with_capacity(escaped.len());
    let mut i = 0;
    while i < escaped.len() {
        if let Some((keep, len)) = autolink_at(&escaped, i) {
            out.extend(&escaped[i..i + keep]);
            out.push('\u{200b}');
            out.extend(&escaped[i + keep..i + len]);
            i += len;
        } else {
            out.push(escaped[i]);
            i += 1;
        }
    }
    out
}

/// Text as a code span, shown as written and never a link: line breaks
/// fold to a space, controls are dropped, `|` is `\|` in a table, and the
/// fence is one backtick longer than the longest run inside, padded with a
/// space when the text starts or ends with a backtick or a space (an empty
/// text is an em dash). As the Python's `_md_code`.
fn md_code(text: &str, in_table: bool) -> String {
    let mut text: String = folded_text(text).into_iter().collect();
    if in_table {
        text = text.replace('|', "\\|");
    }
    if text.is_empty() {
        return "\u{2014}".to_owned();
    }
    let longest = text
        .split(|c| c != '`')
        .map(str::len)
        .max()
        .unwrap_or_default();
    let fence = "`".repeat(longest + 1);
    let edge = |c: Option<char>| matches!(c, Some('`' | ' '));
    let pad = if (edge(text.chars().next()) || edge(text.chars().last()))
        && !text.trim_matches(' ').is_empty()
    {
        " "
    } else {
        ""
    };
    format!("{fence}{pad}{text}{pad}{fence}")
}

fn resources_cell(node: &Value, empty: &str, in_table: bool) -> String {
    let mut cells: Vec<String> = list(&node["holds"])
        .iter()
        .map(|k| md_code(str_of(k), in_table))
        .collect();
    cells.extend(list(&node["meters"]).iter().map(|m| {
        md_code(
            &format!("{}*{}", str_of(&m["name"]), scalar(&m["slots"])),
            in_table,
        )
    }));
    if cells.is_empty() {
        empty.to_owned()
    } else {
        cells.join(", ")
    }
}

fn issue_link(node: &Value) -> String {
    let id = str_of(&node["id"]);
    match node["url"].as_str() {
        Some(url) if !url.is_empty() => format!("[{id}]({url})"),
        _ => id.to_owned(),
    }
}

/// The Python's `--emit-roadmap` block.
fn roadmap_block(document: &Value) -> String {
    let m = &document["metrics"];
    let src = &document["source"];
    let hash: String = str_of(&document["meta"]["artifact_hash"])
        .chars()
        .take(16)
        .collect();
    let roots = joined(list(&src["roots"]), ", ");
    let roots = if roots.is_empty() {
        "all open home issues".to_owned()
    } else {
        roots
    };
    let containers: Vec<&str> = list(&src["containers_excluded"])
        .iter()
        .map(|c| str_of(&c["id"]))
        .collect();
    let band = if m["edge_density_band_ok"] == Value::Bool(true) {
        "in"
    } else {
        "outside"
    };
    let mut out: Vec<String> = vec![ROADMAP_BEGIN.to_owned(), String::new()];
    out.push(format!(
        "Compiled from issue frontmatter (`{}`), home `{}`, roots `{roots}`. Artifact hash `{hash}`. \
         Regenerate with `taskalisk.py --from-github [--root <ref>] --emit-roadmap`.",
        str_of(&src["schema"]),
        str_of(&src["repository"]),
    ));
    out.extend(
        [
            "",
            "## DAG Structural Health",
            "",
            "| Metric | Value |",
            "| --- | --- |",
        ]
        .map(str::to_owned),
    );
    out.push(format!("| Open nodes | {} |", scalar(&m["open_node_count"])));
    out.push(format!(
        "| Reduced edges (raw) | {} ({}) |",
        scalar(&m["reduced_open_edge_count"]),
        scalar(&m["raw_open_edge_count"])
    ));
    out.push(format!(
        "| Edge density | {} ({band} band 0.01\u{2013}0.50) |",
        scalar(&m["edge_density"])
    ));
    out.push(format!(
        "| Max parallel width | {} |",
        scalar(&m["max_parallel_width"])
    ));
    out.push(format!(
        "| Critical path ({}) | {} |",
        scalar(&m["critical_path_length"]),
        joined(list(&m["critical_path"]), " \u{2192} ")
    ));
    out.push(format!(
        "| Isolated nodes | {} |",
        scalar(&m["isolated_open_node_count"])
    ));
    out.push(format!(
        "| Containers excluded | {} |",
        if containers.is_empty() {
            "none".to_owned()
        } else {
            containers.join(", ")
        }
    ));
    out.extend(
        [
            "",
            "## Ranked Open Frontier (Wave 0)",
            "",
            "| Rank | Score | Issue | Title | Status | Unblocks | Depth | Resources | Directly unlocks |",
            "| ---: | ---: | --- | --- | --- | ---: | ---: | --- | --- |",
        ]
        .map(str::to_owned),
    );
    for (i, n) in list(&document["open_frontier_ranked"]).iter().enumerate() {
        let unlocks = joined(list(&n["directly_unlocks"]), ", ");
        out.push(format!(
            "| {} | {} | {} | {} | {} | {} | {} | {} | {} |",
            i + 1,
            scalar(&n["priority_score"]),
            issue_link(n),
            md_cell(title(n)),
            str_of(&n["status"]),
            scalar(&n["transitive_unblocks_count"]),
            scalar(&n["critical_path_remaining_depth"]),
            resources_cell(n, "\u{2014}", true),
            if unlocks.is_empty() {
                "\u{2014}".to_owned()
            } else {
                unlocks
            },
        ));
    }
    out.extend(["", "### Conflict-Free git-locks Batch", ""].map(str::to_owned));
    for b in list(&document["conflict_free_frontier_batch"]) {
        out.push(format!(
            "- {} {} \u{2014} {}",
            issue_link(b),
            md_cell(title(b)),
            resources_cell(b, "no resources", false)
        ));
    }
    out.extend(["", "## Task Checklist by Wave", ""].map(str::to_owned));
    let waves = waves(document);
    for (name, items) in &waves {
        out.push(format!("### {name}"));
        out.push(String::new());
        for n in *items {
            out.push(format!(
                "- [ ] {} {} ({})",
                issue_link(n),
                md_cell(title(n)),
                str_of(&n["status"])
            ));
        }
        out.push(String::new());
    }
    out.extend(["## Task Checklist by Workstream (`area:*`)", ""].map(str::to_owned));
    let mut streams: BTreeMap<&str, Vec<&Value>> = BTreeMap::new();
    for (_, items) in &waves {
        for n in *items {
            let ws = match str_of(&n["workstream"]) {
                "" => "unassigned",
                ws => ws,
            };
            streams.entry(ws).or_default().push(n);
        }
    }
    for (ws, mut nodes) in streams {
        out.push(format!("### {ws}"));
        out.push(String::new());
        nodes.sort_by_cached_key(|n| id_order(str_of(&n["id"])));
        for n in nodes {
            out.push(format!("- [ ] {} {}", issue_link(n), md_cell(title(n))));
        }
        out.push(String::new());
    }
    out.extend(
        [
            "## Transitively-Reduced Dependency DAG",
            "",
            "```mermaid",
            &flowchart(document),
            "```",
            "",
            "## Prerequisite Edge Accounting",
            "",
            "| Blocker | Blocked | Evidence |",
            "| --- | --- | --- |",
        ]
        .map(str::to_owned),
    );
    for e in list(&document["edges"]) {
        out.push(format!(
            "| {} | {} | {} |",
            str_of(&e["from"]),
            str_of(&e["to"]),
            md_cell(str_of(&e["evidence"]))
        ));
    }
    let redundant = list(&document["transitive_redundant_edges_removed"]);
    if !redundant.is_empty() {
        out.extend(
            [
                "",
                "Recorded on GitHub but implied by a longer path (kept there as evidence, omitted from the reduced DAG):",
                "",
            ]
            .map(str::to_owned),
        );
        for e in redundant {
            out.push(format!(
                "- {} \u{2192} {} (via {})",
                str_of(&e["from"]),
                str_of(&e["to"]),
                str_of(&e["implied_via"])
            ));
        }
    }
    out.push(String::new());
    out.push(ROADMAP_END.to_owned());
    out.join("\n")
}

#[cfg(test)]
mod tests {
    use super::{label, md_cell, md_code, node_key};

    /// Each expected text is what the Python's `_md_cell` writes for the
    /// same input.
    #[test]
    fn a_cell_is_what_python_writes() {
        let cases = [
            ("plain", "plain"),
            ("a | b", "a \\| b"),
            ("<b>x</b>", "&lt;b&gt;x&lt;/b&gt;"),
            ("[l](u)", "\\[l\\](u)"),
            ("back\\slash", "back\\\\slash"),
            ("a\r\nb\nc\u{2028}d", "a b c d"),
            ("\u{202e}x\u{1b}y\0", "xy"),
            ("&#64; &#x40; &amp; & &;", "&amp;#64; &amp;#x40; &amp;amp; & &;"),
            ("https://e.x HTTP://e.x", "https:\u{200b}//e.x HTTP:\u{200b}//e.x"),
            ("a.www.b WWW.x", "a.www\u{200b}.b WWW\u{200b}.x"),
            ("x@y @ z", "x@\u{200b}y @ z"),
            ("\u{17f}x://y", "\u{17f}x:\u{200b}//y"),
            ("1http://x", "1http:\u{200b}//x"),
        ];
        for (text, python) in cases {
            assert_eq!(md_cell(text), python, "{text:?}");
        }
    }

    /// Each expected text is what the Python's `_md_code` writes.
    #[test]
    fn a_code_span_is_what_python_writes() {
        let cases = [
            ("k", false, "`k`"),
            ("a`b", false, "``a`b``"),
            ("`x", false, "`` `x ``"),
            ("a|b", true, "`a\\|b`"),
            ("a|b", false, "`a|b`"),
            ("", false, "\u{2014}"),
            ("\u{1b}", false, "\u{2014}"),
            ("  ", false, "`  `"),
            ("a\nb", false, "`a b`"),
        ];
        for (text, in_table, python) in cases {
            assert_eq!(md_code(text, in_table), python, "{text:?}");
        }
    }

    #[test]
    fn a_label_is_one_safe_line() {
        let long = "x".repeat(60);
        let cases = [
            ("t", "o/r#1: t"),
            ("a \"b\" <c> [d] {e}", "o/r#1: a 'b' (c) (d) (e)"),
            ("a\nb\r\n\tc\u{2028}d\u{1c}e", "o/r#1: a b c d e"),
            ("%%{init: {}}%%", "o/r#1: %%(init: ())%%"),
            ("\u{202e}x\0y", "o/r#1: xy"),
            ("", "o/r#1:"),
        ];
        for (title, want) in cases {
            assert_eq!(label("o/r#1", title), want, "{title:?}");
        }
        assert_eq!(
            label("o/r#1", &long),
            format!("o/r#1: {}...", "x".repeat(45))
        );
    }

    #[test]
    fn node_keys_never_collide() {
        assert_eq!(node_key("o/r#1"), "N_o_2fr_231");
        assert_ne!(node_key("a/b-c#1"), node_key("a/b_c#1"));
        assert_ne!(node_key("a/b.c#1"), node_key("a/b_c#1"));
    }
}
