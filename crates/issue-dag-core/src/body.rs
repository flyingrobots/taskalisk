//! Body warnings (flyingrobots/taskalisk#48).
//!
//! Taskalisk's own convention for a task body,
//! `skills/taskalisk/WRITING-TASKS.md`: the sections every canonical template
//! opens with, and the signs that a task carries more than one outcome. This
//! is not part of the `issue-dag/2` format, so the codes carry the prefix
//! `taskalisk.`, and the warnings never affect validity.
//!
//! # How a body is read
//!
//! - **Headings.** A section is found by an ATX heading of level 2 whose text
//!   is exactly `Outcome`, `Scope` or `Acceptance`: case-sensitive, nothing
//!   after the name except an optional closing `#` sequence, with up to three
//!   spaces of indent and any spaces or tabs around the text. So
//!   `## Out of scope` is not Scope, and `# Outcome`, `### Outcome` and
//!   `## outcome` are not Outcome. Setext headings are not read.
//! - **Hidden text.** Lines inside a fenced code block (three or more
//!   backticks or tildes, which includes the frontmatter block) and text
//!   inside an HTML comment are not read, as GitHub does not render them.
//! - **The Outcome section** runs from its heading (the first, if there are
//!   several) to the next heading of level 1 or 2. A line starting with `-`,
//!   `*`, `+`, or a number and `.` or `)`, then a space, is a list item;
//!   other lines are prose, and an indented line after an item continues
//!   it. More than one item is `taskalisk.outcome-items`.
//! - **Sentences.** Inline code spans are skipped. A sentence ends at `.`,
//!   `!` or `?` (after any closing quote or bracket) followed by whitespace
//!   and an uppercase letter; each paragraph of prose holds at least one.
//!   More than one sentence in the prose, or in any single item, is
//!   `taskalisk.outcome-sentences`. So `e.g. a block` and `v1.2` do not
//!   end a sentence, and two paragraphs are two sentences.
//! - **The title**, when given, joins two things when, outside inline code,
//!   it holds a `;` or the word `and` (any ASCII case) between two other
//!   words. The observation bundle records no titles, so a caller without
//!   one passes `None` and this check is skipped.
//!
//! Only a valid document of `.kind: task` is checked: a container, a body
//! without a document, and an invalid document have no body warnings, as an
//! invalid document reports no warnings of its own. Deciding whether a task
//! is atomic, and any threshold on acceptance items, are out of scope.

use crate::finding::{Finding, Severity};
use crate::record::Kind;
use crate::reference::IssueRef;
use crate::{Judgement, admit};

/// Declares [`BodyWarning`], its code and message, its list
/// [`BODY_WARNINGS`] and the count from one list, so a variant cannot exist
/// without its code. The list is written in the order of the codes' text,
/// which is the derived [`Ord`].
macro_rules! body_warnings {
    ($($(#[doc = $doc:literal])* $name:ident => $code:literal, $message:literal,)+) => {
        /// A sign that a task body departs from Taskalisk's writing
        /// convention. Each is a warning; none affects validity.
        #[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub enum BodyWarning {
            $($(#[doc = $doc])* $name,)+
        }

        impl BodyWarning {
            /// The stable code, such as `"taskalisk.outcome-missing"`
            /// (tabled on [`crate::code`]).
            #[must_use]
            pub const fn code(self) -> &'static str {
                match self {
                    $(Self::$name => $code,)+
                }
            }

            /// Fixed text naming the section or the sign, never body text.
            const fn message(self) -> &'static str {
                match self {
                    $(Self::$name => $message,)+
                }
            }
        }

        /// The number of body warnings.
        const COUNT: usize = [$($code),+].len();

        /// Every body warning, once each, in the order of its code's text.
        pub const BODY_WARNINGS: [BodyWarning; COUNT] = [$(BodyWarning::$name),+];

        /// The codes of [`BODY_WARNINGS`] with their severity, in its order:
        /// this family's entry in [`crate::CODES`].
        pub const BODY_CODES: [(&str, Severity); COUNT] =
            [$(($code, Severity::Warning)),+];
    };
}

body_warnings! {
    /// No `## Acceptance` heading.
    AcceptanceMissing => "taskalisk.acceptance-missing",
        "the body has no `## Acceptance` heading (exact text, level 2)",
    /// The Outcome section has more than one list item.
    OutcomeItems => "taskalisk.outcome-items",
        "the Outcome section has more than one list item: the task may carry more than one outcome",
    /// No `## Outcome` heading.
    OutcomeMissing => "taskalisk.outcome-missing",
        "the body has no `## Outcome` heading (exact text, level 2)",
    /// The Outcome section has more than one sentence.
    OutcomeSentences => "taskalisk.outcome-sentences",
        "the Outcome section has more than one sentence: the task may carry more than one outcome",
    /// No `## Scope` heading.
    ScopeMissing => "taskalisk.scope-missing",
        "the body has no `## Scope` heading (exact text, level 2)",
    /// The title joins two things with `and` or a semicolon.
    TitleJoins => "taskalisk.title-joins",
        "the title joins two things with \"and\" or a semicolon: the task may carry more than one \
         outcome",
}

/// The body warnings of the issue at `address`, sorted by code.
///
/// `title` is the issue's title; with `None` the title check is skipped.
/// Every finding is a warning whose subject is the address. Only a valid
/// task document is checked (see the module documentation for how a body is
/// read).
#[must_use]
pub fn body_warnings(body: &str, address: &IssueRef, title: Option<&str>) -> Vec<Finding> {
    let is_task = matches!(
        admit(body, Some(address)),
        Judgement::Valid { ref record, .. } if record.kind == Kind::Task
    );
    if !is_task {
        return Vec::new();
    }
    let lines = visible_lines(body);
    let mut found = Vec::new();
    for (name, warning) in [
        ("Acceptance", BodyWarning::AcceptanceMissing),
        ("Scope", BodyWarning::ScopeMissing),
    ] {
        if section(&lines, name).is_none() {
            found.push(warning);
        }
    }
    match section(&lines, "Outcome") {
        None => found.push(BodyWarning::OutcomeMissing),
        Some(outcome) => {
            let shape = Shape::of(outcome);
            if shape.items > 1 {
                found.push(BodyWarning::OutcomeItems);
            }
            if shape.prose_sentences > 1 || shape.most_item_sentences > 1 {
                found.push(BodyWarning::OutcomeSentences);
            }
        }
    }
    if title.is_some_and(joins_two) {
        found.push(BodyWarning::TitleJoins);
    }
    let mut findings: Vec<Finding> = found
        .into_iter()
        .map(|warning| Finding {
            subject: address.clone(),
            code: warning.code(),
            severity: Severity::Warning,
            message: warning.message(),
        })
        .collect();
    findings.sort();
    findings
}

/// The lines of a body as rendered text: `None` for a line that is hidden
/// (in or delimiting a fenced code block, or wholly inside an HTML comment),
/// otherwise the line without its comments and its line end.
fn visible_lines(body: &str) -> Vec<Option<String>> {
    let mut fence: Option<(char, usize)> = None;
    let mut in_comment = false;
    let mut out = Vec::new();
    for raw in body.lines() {
        let line = raw.strip_suffix('\r').unwrap_or(raw);
        if let Some((mark, open)) = fence {
            if fence_run(line)
                .is_some_and(|(c, n, rest)| c == mark && n >= open && rest.trim().is_empty())
            {
                fence = None;
            }
            out.push(None);
            continue;
        }
        if !in_comment && let Some((mark, n, _)) = fence_run(line) {
            fence = Some((mark, n));
            out.push(None);
            continue;
        }
        let was_blank = line.trim().is_empty();
        let text = strip_comments(line, &mut in_comment);
        out.push((was_blank || !text.trim().is_empty()).then_some(text));
    }
    out
}

/// The fence character, the length of its run and the rest of the line, when
/// the line opens or may close a fenced code block.
fn fence_run(line: &str) -> Option<(char, usize, &str)> {
    let text = unindent(line)?;
    let mark = text.chars().next().filter(|c| matches!(c, '`' | '~'))?;
    let n = text.chars().take_while(|&c| c == mark).count();
    (n >= 3).then(|| (mark, n, &text[n..]))
}

/// The line without up to three spaces of indent, or `None` when it is
/// indented further (an indented code line, never a heading or a fence).
fn unindent(line: &str) -> Option<&str> {
    let spaces = line.bytes().take_while(|&b| b == b' ').count();
    (spaces <= 3).then(|| &line[spaces..])
}

/// The line without the text of HTML comments, carrying whether a comment
/// is still open at its end.
fn strip_comments(line: &str, in_comment: &mut bool) -> String {
    let mut out = String::new();
    let mut rest = line;
    loop {
        if *in_comment {
            let Some(end) = rest.find("-->") else {
                return out;
            };
            rest = &rest[end + 3..];
            *in_comment = false;
        } else {
            let Some(start) = rest.find("<!--") else {
                out.push_str(rest);
                return out;
            };
            out.push_str(&rest[..start]);
            rest = &rest[start + 4..];
            *in_comment = true;
        }
    }
}

/// The level and text of an ATX heading line, its closing sequence removed.
fn heading(line: &str) -> Option<(usize, &str)> {
    let text = unindent(line)?;
    let level = text.bytes().take_while(|&b| b == b'#').count();
    if !(1..=6).contains(&level) {
        return None;
    }
    let rest = &text[level..];
    if !(rest.is_empty() || rest.starts_with([' ', '\t'])) {
        return None;
    }
    let rest = rest.trim();
    let unclosed = rest.trim_end_matches('#');
    let content = if unclosed.is_empty() || unclosed.ends_with([' ', '\t']) {
        unclosed.trim_end()
    } else {
        rest
    };
    Some((level, content))
}

/// The lines of the first level-2 section named exactly `name`, up to the
/// next heading of level 1 or 2; `None` when there is no such heading.
fn section<'a>(lines: &'a [Option<String>], name: &str) -> Option<&'a [Option<String>]> {
    let start = lines
        .iter()
        .position(|l| l.as_deref().and_then(heading) == Some((2, name)))?
        + 1;
    let len = lines[start..]
        .iter()
        .position(|l| {
            l.as_deref()
                .and_then(heading)
                .is_some_and(|(level, _)| level <= 2)
        })
        .unwrap_or(lines.len() - start);
    Some(&lines[start..start + len])
}

/// What an Outcome section holds.
struct Shape {
    /// The number of list items.
    items: usize,
    /// The sentences of its prose, over all paragraphs.
    prose_sentences: usize,
    /// The sentences of its longest item.
    most_item_sentences: usize,
}

impl Shape {
    fn of(lines: &[Option<String>]) -> Self {
        let mut items: Vec<String> = Vec::new();
        let mut paragraphs: Vec<String> = Vec::new();
        // Where the next continuation line goes.
        let mut open: Option<Unit> = None;
        for line in lines.iter().flatten() {
            if line.trim().is_empty() {
                open = None;
            } else if let Some(text) = list_item(line) {
                items.push(text.to_owned());
                open = Some(Unit::Item);
            } else if line.starts_with([' ', '\t'])
                && !items.is_empty()
                && open != Some(Unit::Prose)
            {
                push_line(items.last_mut(), line);
                open = Some(Unit::Item);
            } else if open == Some(Unit::Item) {
                push_line(items.last_mut(), line);
            } else if open == Some(Unit::Prose) {
                push_line(paragraphs.last_mut(), line);
            } else {
                paragraphs.push(line.trim().to_owned());
                open = Some(Unit::Prose);
            }
        }
        Self {
            items: items.len(),
            prose_sentences: paragraphs.iter().map(|p| sentences(p)).sum(),
            most_item_sentences: items.iter().map(|i| sentences(i)).max().unwrap_or(0),
        }
    }
}

/// The kind of unit a continuation line joins.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Unit {
    Item,
    Prose,
}

fn push_line(unit: Option<&mut String>, line: &str) {
    if let Some(unit) = unit {
        unit.push(' ');
        unit.push_str(line.trim());
    }
}

/// The text of a list item line, or `None` when the line is not one.
fn list_item(line: &str) -> Option<&str> {
    let text = line.trim_start();
    let digits = text.bytes().take_while(u8::is_ascii_digit).count();
    let marker = match text.as_bytes() {
        [b'-' | b'*' | b'+', ..] => 1,
        _ if (1..=9).contains(&digits)
            && matches!(text.as_bytes().get(digits), Some(b'.' | b')')) =>
        {
            digits + 1
        }
        _ => return None,
    };
    let rest = &text[marker..];
    (rest.is_empty() || rest.starts_with([' ', '\t'])).then(|| rest.trim())
}

/// The text without its inline code spans.
fn without_code(text: &str) -> String {
    text.split('`').step_by(2).collect::<Vec<_>>().join(" ")
}

/// The number of sentences in a paragraph or an item: zero when it has no
/// letter or digit, otherwise one more than its sentence ends.
fn sentences(text: &str) -> usize {
    let text = without_code(text);
    if !text.chars().any(char::is_alphanumeric) {
        return 0;
    }
    let chars: Vec<char> = text.chars().collect();
    let mut ends = 0;
    let mut i = 0;
    while i < chars.len() {
        if matches!(chars[i], '.' | '!' | '?') {
            let mut j = i + 1;
            while j < chars.len()
                && matches!(chars[j], '"' | '\'' | ')' | ']' | '\u{201d}' | '\u{2019}')
            {
                j += 1;
            }
            let gap = chars[j..].iter().take_while(|c| c.is_whitespace()).count();
            if gap > 0 && chars.get(j + gap).is_some_and(|c| c.is_uppercase()) {
                ends += 1;
            }
            i = j;
        } else {
            i += 1;
        }
    }
    ends + 1
}

/// Whether a title joins two things: a `;`, or the word `and` between two
/// other words, outside inline code.
fn joins_two(title: &str) -> bool {
    let title = without_code(title);
    let words: Vec<&str> = title.split_whitespace().collect();
    title.contains(';')
        || words.len() >= 3
            && words[1..words.len() - 1]
                .iter()
                .any(|w| w.eq_ignore_ascii_case("and"))
}
