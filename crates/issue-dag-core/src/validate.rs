//! Key binding and validity (format sections 3 to 5) and the record (M4).

use std::collections::BTreeSet;

use crate::carrier::{Block, Value};
use crate::label::Label;
use crate::record::{Kind, MeterClaim, Record, Status, TaskType, VERSION};
use crate::reference::{IssueRef, MAX_NUMBER, parse_number};

/// The format keys of `issue-dag/2` (rule M2).
pub const FORMAT_KEYS: [&str; 10] = [
    ".dag",
    ".id",
    ".kind",
    ".type",
    ".blocked_by",
    ".children",
    ".size_hours",
    ".holds",
    ".meters",
    ".status",
];

/// The violations and warnings of a document.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Validation {
    /// The labels of the rules the document fails, each once (rule V12).
    pub violations: BTreeSet<Label>,
    /// The labels of its warnings (rule V10).
    pub warnings: BTreeSet<Label>,
}

impl Validation {
    fn fail(&mut self, label: Label) {
        self.violations.insert(label);
    }
}

/// Validates a block. With an address, `.id` is also judged under profile
/// rule X1.
#[must_use]
pub fn validate(block: &Block, address: Option<&IssueRef>) -> Validation {
    decode(block, address).0
}

/// Validates a block and, when `.id` and `.kind` have values of the right
/// form, decodes the record. The record is meaningful only when the
/// validation has no violations.
pub fn decode(block: &Block, address: Option<&IssueRef>) -> (Validation, Option<Record>) {
    let mut v = Validation {
        violations: block.violations().clone(),
        warnings: BTreeSet::new(),
    };
    if names_another_version(block, &mut v) {
        // Judged under the version policy, not by this format: P3 alone.
        return (
            Validation {
                violations: BTreeSet::from([Label::P3]),
                warnings: BTreeSet::new(),
            },
            None,
        );
    }
    if block
        .entries()
        .iter()
        .any(|e| e.key.starts_with('.') && !FORMAT_KEYS.contains(&e.key.as_str()))
    {
        v.fail(Label::V2);
    }
    let id = identity(block, address, &mut v);
    let kind = match block.value(".kind") {
        Some(Value::String(text)) => Kind::parse(text),
        _ => None,
    };
    if kind.is_none() {
        v.fail(Label::V4);
    }
    let (task_type, blocked_by, children) = kind_keys(block, kind, &mut v);
    if let Some(id) = &id
        && blocked_by
            .iter()
            .chain(children.iter())
            .flatten()
            .any(|r| r == id)
    {
        v.fail(Label::V7);
    }
    let size_hours = size_hours(block, &mut v);
    let holds = holds(block, &mut v);
    let meters = meters(block, &mut v);
    let status = status(block, &mut v);
    let record = match (id, kind) {
        (Some(id), Some(kind)) => Some(Record {
            id,
            kind,
            task_type,
            blocked_by,
            children,
            size_hours,
            holds,
            meters,
            status,
        }),
        _ => None,
    };
    (v, record)
}

/// V1 and P3. Returns whether `.dag` names a format version other than this
/// one.
fn names_another_version(block: &Block, v: &mut Validation) -> bool {
    match block.value(".dag") {
        Some(Value::String(version)) if version == VERSION => false,
        Some(Value::String(version)) if is_format_name(version) => true,
        _ => {
            v.fail(Label::V1);
            false
        }
    }
}

/// V3, L1 and X1 for `.id`.
fn identity(block: &Block, address: Option<&IssueRef>, v: &mut Validation) -> Option<IssueRef> {
    let Some(Value::String(text)) = block.value(".id") else {
        v.fail(Label::V3);
        return None;
    };
    let Some(id) = IssueRef::parse(text) else {
        v.fail(Label::L1);
        return None;
    };
    if address.is_some_and(|address| *address != id) {
        v.fail(Label::X1);
    }
    Some(id)
}

type KindKeys = (
    Option<TaskType>,
    Option<Vec<IssueRef>>,
    Option<Vec<IssueRef>>,
);

/// V5 and V6: `.type`, `.blocked_by` and `.children`, which the kind
/// governs. With no valid kind they are not judged.
fn kind_keys(block: &Block, kind: Option<Kind>, v: &mut Validation) -> KindKeys {
    match kind {
        Some(Kind::Task) => {
            let task_type = match block.value(".type") {
                Some(Value::String(text)) => TaskType::parse(text),
                _ => None,
            };
            if task_type.is_none() {
                v.fail(Label::V5);
            }
            let blocked_by = references(block.value(".blocked_by"), Label::V5, v);
            if block.value(".children").is_some() {
                v.fail(Label::V5);
            }
            (task_type, blocked_by, None)
        }
        Some(Kind::Container) => {
            let task_type = block
                .value(".type")
                .and_then(|value| one_of(value, TaskType::parse, Label::V6, v));
            let children = references(block.value(".children"), Label::V6, v);
            if block.value(".blocked_by").is_some() {
                v.fail(Label::V6);
            }
            (task_type, None, children)
        }
        None => (None, None, None),
    }
}

/// A list of references for a key the kind requires: a missing or wrongly
/// kinded value is labelled `rule`, an item that is not a reference L1.
fn references(value: Option<&Value>, rule: Label, v: &mut Validation) -> Option<Vec<IssueRef>> {
    let Some(Value::List(items)) = value else {
        v.fail(rule);
        return None;
    };
    let refs: Vec<IssueRef> = items.iter().filter_map(|i| IssueRef::parse(i)).collect();
    if refs.len() != items.len() {
        v.fail(Label::L1);
    }
    Some(refs)
}

/// V8, L4 and V10 for `.size_hours`.
fn size_hours(block: &Block, v: &mut Validation) -> Option<u32> {
    let Value::Integer(n) = block.value(".size_hours")? else {
        v.fail(Label::V8);
        return None;
    };
    let hours = n
        .to_i64()
        .and_then(|n| u32::try_from(n).ok())
        .filter(|n| (1..=MAX_NUMBER).contains(n));
    match hours {
        None => v.fail(Label::L4),
        Some(h) if h > 8 => {
            v.warnings.insert(Label::V10);
        }
        Some(_) => {}
    }
    hours
}

/// V8 and L2 for `.holds`.
fn holds(block: &Block, v: &mut Validation) -> BTreeSet<String> {
    match block.value(".holds") {
        None => BTreeSet::new(),
        Some(Value::List(items)) => {
            if items.iter().any(String::is_empty) {
                v.fail(Label::L2);
            }
            items.iter().filter(|i| !i.is_empty()).cloned().collect()
        }
        Some(_) => {
            v.fail(Label::V8);
            BTreeSet::new()
        }
    }
}

/// V8 and L3 for `.meters`.
fn meters(block: &Block, v: &mut Validation) -> Vec<MeterClaim> {
    match block.value(".meters") {
        None => Vec::new(),
        Some(Value::List(items)) => {
            let claims: Vec<MeterClaim> =
                items.iter().filter_map(|i| MeterClaim::parse(i)).collect();
            if claims.len() != items.len() {
                v.fail(Label::L3);
            }
            claims
        }
        Some(_) => {
            v.fail(Label::V8);
            Vec::new()
        }
    }
}

/// V8 for `.status`.
fn status(block: &Block, v: &mut Validation) -> Option<Status> {
    block
        .value(".status")
        .and_then(|value| one_of(value, Status::parse, Label::V8, v))
}

/// A string that must be one of a set of values: anything else, or a value
/// that is not a string, is labelled `rule`.
fn one_of<T>(
    value: &Value,
    parse: fn(&str) -> Option<T>,
    rule: Label,
    v: &mut Validation,
) -> Option<T> {
    let found = match value {
        Value::String(text) => parse(text),
        _ => None,
    };
    if found.is_none() {
        v.fail(rule);
    }
    found
}

/// A format name: `issue-dag/` followed by a number as in rule L1.
fn is_format_name(text: &str) -> bool {
    text.strip_prefix("issue-dag/")
        .and_then(parse_number)
        .is_some()
}
