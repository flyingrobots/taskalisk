//! What the renderer's tests share: the fixtures captured from the Python
//! by `tests/capture_render_parity.py`, the bundles they plan, and the
//! display input read from the Python's lines.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use issue_dag_bundle::load;
use issue_dag_core::{IssueRef, Outcome, Parameters, RecordedForge, plan};
use serde_json::Value;
use taskalisk::render::Display;

pub fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

pub fn fixtures() -> PathBuf {
    root().join("tests/fixtures/render")
}

/// The bundle a fixture plans: a variant's, written by
/// `tests/capture_render_parity.py` beside the fixtures, or a corpus
/// case's; `<case>--titles` is `<case>` with titles that hold what JSON
/// must escape or what attacks a rendered view.
pub fn bundle_text(case: &str) -> String {
    let variant = |name: &str| fixtures().join("bundles").join(format!("{name}.json"));
    if let Ok(text) = fs::read_to_string(variant(case)) {
        return text;
    }
    let case = case.strip_suffix("--titles").unwrap_or(case);
    if let Ok(text) = fs::read_to_string(variant(case)) {
        return text;
    }
    let path = root()
        .join("tests/fixtures/issue-dag/corpus/cases/graph")
        .join(case)
        .join("bundle.json");
    fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// A fixture's bundle, planned by `issue-dag-core` from its recorded
/// observations.
pub fn planned(case: &str) -> Result<(Parameters, Outcome), String> {
    let bundle = load(&bundle_text(case)).map_err(|e| format!("bundle rejected: {e}"))?;
    let forge = RecordedForge::new(&bundle.observations);
    let outcome = plan(&bundle.parameters, &forge).map_err(|e| e.to_string())?;
    Ok((bundle.parameters, outcome))
}

pub fn lines(text: &str) -> Vec<Value> {
    text.lines()
        .map(|l| serde_json::from_str(l).unwrap_or_else(|e| panic!("{e}: {l}")))
        .collect()
}

/// The fixtures, by name: one per Python capture.
pub fn cases() -> Vec<String> {
    let mut names: Vec<String> = fs::read_dir(fixtures().join("python"))
        .expect("the Python fixtures are present")
        .filter_map(|e| {
            let name = e.expect("entry").file_name().into_string().expect("UTF-8");
            name.strip_suffix(".jsonl").map(str::to_owned)
        })
        .collect();
    names.sort();
    names
}

/// The Python's result lines for a fixture.
pub fn python(case: &str) -> Vec<Value> {
    let path = fixtures().join("python").join(format!("{case}.jsonl"));
    lines(&fs::read_to_string(path).expect("the Python fixture"))
}

fn text(value: &Value) -> Option<String> {
    value.as_str().map(str::to_owned)
}

fn reference(value: &Value) -> Option<IssueRef> {
    value.as_str().and_then(IssueRef::parse)
}

fn string_lists(value: &Value) -> BTreeMap<String, Vec<String>> {
    value
        .as_object()
        .into_iter()
        .flatten()
        .map(|(k, v)| {
            let items = v.as_array().into_iter().flatten().filter_map(text);
            (k.clone(), items.collect())
        })
        .collect()
}

/// The display input the Python's lines show: what the adapters will read.
pub fn display_of(python: &[Value]) -> Display {
    let mut d = Display::default();
    let mut issue = |id: &Value, title: &Value, url: &Value| {
        let Some(id) = reference(id) else { return };
        if let Some(title) = text(title).filter(|t| t != "(untrusted issue)") {
            d.titles.insert(id.clone(), title);
        }
        if let Some(url) = text(url) {
            d.urls.insert(id, url);
        }
    };
    for line in python {
        let detail = &line["detail"];
        match (line["event"].as_str(), line["code"].as_str()) {
            (Some("frontier_node" | "node"), _) => {
                issue(&line["id"], &line["title"], &line["url"]);
            }
            (Some("finding"), Some("container.excluded" | "issue.unmodeled" | "issue.opaque")) => {
                issue(&detail["id"], &detail["title"], &detail["url"]);
            }
            (Some("finding"), Some("parent.not_planned")) => {
                issue(&detail["parent"], &detail["title"], &Value::Null);
            }
            _ => {}
        }
    }
    for line in python {
        if matches!(line["event"].as_str(), Some("frontier_node" | "node")) {
            let Some(id) = reference(&line["id"]) else {
                continue;
            };
            for pr in line["linked_open_prs"].as_array().into_iter().flatten() {
                if let (Some(n), Some(url)) = (pr["number"].as_u64(), text(&pr["url"])) {
                    d.pull_request_urls.insert(n, url);
                }
            }
            let branches: Vec<String> = line["recoverable_branches"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(text)
                .collect();
            if !branches.is_empty() {
                d.recoverable_branches.insert(id, branches);
            }
        }
        if line["event"] == "plan" {
            let trust = &line["source"]["trust"];
            d.codeowners = string_lists(&trust["codeowners"]);
            d.codeowners_teams_not_expanded = string_lists(&trust["codeowners_teams_not_expanded"]);
        }
    }
    d
}

/// Whether the case's 1.x document holds an intended difference or a gap:
/// then the Rust `artifact_hash` digests the Rust document, and is not the
/// Python's (`docs/topics/output/README.md`). Only its form is asserted.
pub fn hash_differs(python: &[Value]) -> bool {
    python[0]["outcome"] != "compiled"
        || python.iter().any(|l| {
            matches!(
                l["code"].as_str(),
                Some(
                    "frontmatter.violation"
                        | "frontmatter.warning"
                        | "issue.untrusted"
                        | "pull_request.untrusted"
                )
            )
        })
}
