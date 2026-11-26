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
//! The body is parsed as `CommonMark` (no extensions) by `pulldown-cmark`,
//! so it is read as it renders, not line by line.
//!
//! - **Headings.** A section is found by a level-2 heading, ATX or setext,
//!   outside any block quote or list, whose rendered text is exactly
//!   `Outcome`, `Scope` or `Acceptance` and holds nothing but plain text:
//!   case-sensitive, with no code, emphasis, link or HTML. So
//!   `## Out of scope` and `## **Scope**` are not Scope, and `# Outcome`,
//!   `### Outcome` and `## outcome` are not Outcome.
//! - **Hidden text.** Code blocks (which include the frontmatter block),
//!   inline code spans and HTML, comments included, add no text.
//! - **The Outcome section** runs from its heading (the first, if there are
//!   several) to the next heading of level 1 or 2. Every list item in it, at
//!   any depth, counts; more than one is `taskalisk.outcome-items`. An
//!   item's text is that of its own paragraphs; each paragraph or lower
//!   heading outside a list is a prose paragraph.
//! - **Sentences.** A sentence ends at `.`, `!` or `?` (after any closing
//!   quote or bracket) followed by whitespace and an uppercase letter; each
//!   prose paragraph holds at least one. More than one sentence over all the
//!   prose paragraphs, or in any single item, is
//!   `taskalisk.outcome-sentences`. So `e.g. a block` and `v1.2` do not end
//!   a sentence, and two paragraphs (separated by a blank line, a code block
//!   or anything else that ends a `CommonMark` paragraph) are two sentences.
//! - **The title**, when given, is read as inline Markdown and joins two
//!   things when, outside code spans, it holds a `;` or the word `and` (any
//!   ASCII case) between two other words. The observation bundle records no
//!   titles, so a caller without one passes `None` and this check is skipped.
//!
//! Only a valid document of `.kind: task` is checked: a container, a body
//! without a document, and an invalid document have no body warnings, as an
//! invalid document reports no warnings of its own. Deciding whether a task
//! is atomic, and any threshold on acceptance items, are out of scope.

use pulldown_cmark::{Event, HeadingLevel, Parser, Tag, TagEnd};

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
    let reading = read(body);
    let mut found = Vec::new();
    for (name, warning) in [
        ("Acceptance", BodyWarning::AcceptanceMissing),
        ("Scope", BodyWarning::ScopeMissing),
    ] {
        if !reading.sections.iter().any(|s| s == name) {
            found.push(warning);
        }
    }
    match reading.outcome {
        None => found.push(BodyWarning::OutcomeMissing),
        Some(shape) => {
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
            concerns: None,
            severity: Severity::Warning,
            message: warning.message(),
        })
        .collect();
    findings.sort();
    findings
}

/// The name of the section whose shape is read.
const OUTCOME: &str = "Outcome";

/// A body as `CommonMark` reads it.
struct Reading {
    /// The text of each section heading, in order.
    sections: Vec<String>,
    /// The shape of the first Outcome section, if there is one.
    outcome: Option<Shape>,
}

/// The sections of `body` and the shape of its first Outcome section.
///
/// A section heading is an ATX or setext heading of level 1 or 2 outside any
/// block quote or list. Its text counts only when the heading holds plain
/// text and nothing else (no code, emphasis, link or HTML), so `## **Scope**`
/// names no section. A level-1 heading ends a section and names none.
fn read(body: &str) -> Reading {
    let mut sections = Vec::new();
    let mut outcome = None;
    // The Outline of the Outcome section while it is open.
    let mut open: Option<Outline> = None;
    // A section heading being read: its level, and its text while plain.
    let mut heading: Option<(HeadingLevel, Option<String>)> = None;
    // The block quotes and lists open around the current event.
    let mut depth = 0_usize;
    for event in Parser::new(body) {
        if let Some((level, text)) = &mut heading {
            match event {
                Event::End(TagEnd::Heading(_)) => {
                    if let (HeadingLevel::H2, Some(text)) = (*level, text.take()) {
                        if text == OUTCOME && !sections.iter().any(|s| s == OUTCOME) {
                            open = Some(Outline::default());
                        }
                        sections.push(text);
                    }
                    heading = None;
                }
                Event::Text(t) => {
                    if let Some(text) = text {
                        text.push_str(&t);
                    }
                }
                _ => *text = None,
            }
            continue;
        }
        match &event {
            Event::Start(Tag::Heading { level, .. })
                if depth == 0 && *level <= HeadingLevel::H2 =>
            {
                outcome = outcome.or_else(|| open.take().map(Outline::shape));
                heading = Some((*level, Some(String::new())));
                continue;
            }
            Event::Start(Tag::BlockQuote(_) | Tag::List(_)) => depth += 1,
            Event::End(TagEnd::BlockQuote(_) | TagEnd::List(_)) => {
                depth = depth.saturating_sub(1);
            }
            _ => {}
        }
        if let Some(outline) = &mut open {
            outline.take(&event);
        }
    }
    Reading {
        sections,
        outcome: outcome.or_else(|| open.map(Outline::shape)),
    }
}

/// What an Outcome section holds.
struct Shape {
    /// The number of list items, at any depth.
    items: usize,
    /// The sentences of its prose, over all paragraphs.
    prose_sentences: usize,
    /// The sentences of its longest item.
    most_item_sentences: usize,
}

/// An Outcome section's shape, built from its events.
///
/// Each list item collects the text of its own paragraphs (a nested item is
/// an item of its own); each paragraph or lower heading outside a list is a
/// prose paragraph. Code spans, code blocks and HTML add no text.
#[derive(Default)]
struct Outline {
    items: usize,
    prose_sentences: usize,
    most_item_sentences: usize,
    /// The text of each open item, innermost last.
    open_items: Vec<String>,
    /// The text of the open prose paragraph.
    paragraph: Option<String>,
    /// Whether a code block is open.
    in_code: bool,
}

impl Outline {
    fn take(&mut self, event: &Event<'_>) {
        match event {
            Event::Start(Tag::Item) => {
                self.items += 1;
                self.open_items.push(String::new());
            }
            Event::End(TagEnd::Item) => {
                if let Some(item) = self.open_items.pop() {
                    self.most_item_sentences = self.most_item_sentences.max(sentences(&item));
                }
            }
            Event::Start(Tag::Paragraph | Tag::Heading { .. }) => {
                if self.open_items.is_empty() {
                    self.paragraph = Some(String::new());
                } else {
                    self.push(" ");
                }
            }
            Event::End(TagEnd::Paragraph | TagEnd::Heading(_)) => {
                if let Some(paragraph) = self.paragraph.take() {
                    self.prose_sentences += sentences(&paragraph);
                }
            }
            Event::Start(Tag::CodeBlock(_)) => self.in_code = true,
            Event::End(TagEnd::CodeBlock) => self.in_code = false,
            Event::Text(text) if !self.in_code => self.push(text),
            Event::Code(_) | Event::SoftBreak | Event::HardBreak => self.push(" "),
            _ => {}
        }
    }

    fn push(&mut self, text: &str) {
        if let Some(item) = self.open_items.last_mut() {
            item.push_str(text);
        } else if let Some(paragraph) = &mut self.paragraph {
            paragraph.push_str(text);
        }
    }

    fn shape(self) -> Shape {
        Shape {
            items: self.items,
            prose_sentences: self.prose_sentences,
            most_item_sentences: self.most_item_sentences,
        }
    }
}

/// The rendered text of inline Markdown, each code span a space; code blocks
/// and HTML add no text.
fn plain_text(markdown: &str) -> String {
    let mut out = String::new();
    let mut in_code = false;
    for event in Parser::new(markdown) {
        match event {
            Event::Start(Tag::CodeBlock(_)) => in_code = true,
            Event::End(TagEnd::CodeBlock) => in_code = false,
            Event::Text(text) if !in_code => out.push_str(&text),
            Event::Code(_) | Event::SoftBreak | Event::HardBreak | Event::End(_) => out.push(' '),
            _ => {}
        }
    }
    out
}

/// The number of sentences in a paragraph or an item, its code already
/// removed: zero when it has no letter or digit, otherwise one more than its
/// sentence ends.
fn sentences(text: &str) -> usize {
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
    let title = plain_text(title);
    let words: Vec<&str> = title.split_whitespace().collect();
    title.contains(';')
        || words.len() >= 3
            && words[1..words.len() - 1]
                .iter()
                .any(|w| w.eq_ignore_ascii_case("and"))
}
