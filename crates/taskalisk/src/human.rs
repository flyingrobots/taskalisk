//! `--human`: a plan's lines as prose, as `render_human` in
//! `skills/taskalisk/scripts/taskalisk.py` writes them. Node, wave and edge
//! lines print nothing; the receipt is unchanged.

use std::fmt::Write as _;

use serde_json::Value;

/// C0 and C1 controls, line and paragraph separators and bidirectional
/// overrides: none reaches prose.
const fn unsafe_char(c: char) -> bool {
    matches!(c, '\u{00}'..='\u{1f}' | '\u{7f}'..='\u{9f}' | '\u{2028}' | '\u{2029}' | '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
}

/// GitHub text made safe to print: each unsafe character as `\uXXXX`.
fn hs(value: &Value) -> String {
    let text = value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned);
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        if unsafe_char(c) {
            let _ = write!(out, "\\u{:04x}", u32::from(c));
        } else {
            out.push(c);
        }
    }
    out
}

fn texts(values: &Value) -> Vec<String> {
    values.as_array().into_iter().flatten().map(hs).collect()
}

/// One line as prose: `None` for the writer's default, `Some("")` for
/// nothing.
#[must_use]
pub fn render(line: &Value) -> Option<String> {
    match line["event"].as_str()? {
        "plan" => Some(plan(line)),
        "frontier_node" => Some(format!(
            "{:>4} {:>6}  {:<32} {:<12} {}",
            line["rank"].to_string(),
            line["priority_score"].to_string(),
            hs(&line["id"]),
            hs(&line["status"]),
            hs(&line["title"])
        )),
        "batch" => {
            let members: Vec<String> = line["members"]
                .as_array()
                .into_iter()
                .flatten()
                .map(|b| hs(&b["id"]))
                .collect();
            let mut out = vec![
                String::new(),
                format!(
                    "batch: {}",
                    if members.is_empty() {
                        "(empty)".to_owned()
                    } else {
                        members.join(", ")
                    }
                ),
            ];
            for skip in line["skipped"].as_array().into_iter().flatten() {
                out.push(format!(
                    "  skipped {}: {}",
                    hs(&skip["id"]),
                    hs(&skip["reason"])
                ));
            }
            let unknown = texts(&line["semaphores_with_unknown_capacity_treated_as_1"]);
            if !unknown.is_empty() {
                out.push(format!(
                    "  unknown capacity, treated as 1: {}",
                    unknown.join(", ")
                ));
            }
            Some(out.join("\n"))
        }
        "node" | "wave" | "edge" => Some(String::new()),
        "finding" => {
            let message = line["message"].as_str().unwrap_or_default();
            let about = match line["subject"].as_str() {
                Some(subject) if !message.contains(subject) => format!(" {}", hs(&line["subject"])),
                _ => String::new(),
            };
            // A finding without a message prints its code and subject
            // alone; the renderer words every finding it writes.
            let said = if message.is_empty() {
                String::new()
            } else {
                format!(": {}", hs(&Value::String(message.to_owned())))
            };
            Some(format!("{}{about}{said}", hs(&line["code"])))
        }
        event @ ("error" | "warning") => {
            let remedy = line
                .get("remedy")
                .filter(|r| r.as_str().is_some_and(|r| !r.is_empty()))
                .map_or_else(String::new, |r| format!(" ({})", hs(r)));
            Some(format!(
                "{event} {}: {}{remedy}",
                hs(&line["code"]),
                hs(&line["problem"])
            ))
        }
        "command" => Some(format!("{}: {}", hs(&line["name"]), hs(&line["intent"]))),
        "schema" => Some(format!(
            "schema {} {}",
            hs(&line["id"]),
            hs(&line["version"])
        )),
        _ => None,
    }
}

fn plan(line: &Value) -> String {
    let repository = line["source"]["repository"].as_str().map_or_else(
        || "DAG spec".to_owned(),
        |r| hs(&Value::String(r.to_owned())),
    );
    let mut first = format!("{repository}: {}", hs(&line["outcome"]));
    if line["outcome"] == "compiled" {
        let m = &line["metrics"];
        let batch = line["batch"].as_array().map_or(0, Vec::len);
        let _ = write!(
            first,
            ", {} open node(s), {} on the frontier, a batch of {batch}, critical path {}",
            m["open_node_count"], line["open_frontier_count"], m["critical_path_length"]
        );
    }
    let mut out = vec![first];
    if line["ok"] != Value::Bool(true) {
        out.push(format!(
            "NOT OK ({}): do not dispatch from this plan",
            texts(&line["error_codes"]).join(", ")
        ));
    }
    if line["frontier"].as_array().is_some_and(|f| !f.is_empty()) {
        out.push(String::new());
        out.push(format!(
            "{:>4} {:>6}  {:<32} {:<12} title",
            "rank", "score", "issue", "status"
        ));
    }
    out.join("\n")
}

#[cfg(test)]
mod tests {
    use super::render;
    use serde_json::json;

    #[test]
    fn github_text_cannot_move_the_cursor_or_reorder_the_line() {
        let line = json!({"event": "frontier_node", "rank": 1, "priority_score": 10,
                          "id": "o/r#1", "status": "open", "title": "a\nb\u{202e}c"});
        assert_eq!(
            render(&line).as_deref(),
            Some("   1     10  o/r#1                            open         a\\u000ab\\u202ec")
        );
    }

    #[test]
    fn a_finding_names_its_subject_once() {
        let named = json!({"event": "finding", "code": "x.y", "subject": "o/r#1", "message": "o/r#1 is odd"});
        assert_eq!(render(&named).as_deref(), Some("x.y: o/r#1 is odd"));
        let unnamed =
            json!({"event": "finding", "code": "x.y", "subject": "o/r#1", "message": "odd"});
        assert_eq!(render(&unnamed).as_deref(), Some("x.y o/r#1: odd"));
        assert_eq!(render(&json!({"event": "edge"})).as_deref(), Some(""));
    }
}
