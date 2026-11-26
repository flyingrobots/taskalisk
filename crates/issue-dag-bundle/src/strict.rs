//! JSON read strictly: an object that gives a member twice is refused, at
//! its path. RFC 8259 leaves such an object's meaning to the reader, and
//! `serde_json` would keep the last value without a word, so a bundle could
//! hold two answers to one lookup and be read as either.

use core::fmt;
use std::cell::RefCell;
use std::collections::BTreeSet;

use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value};

use crate::BundleError;

/// Reads JSON text into a value. Paths name the members of the whole value
/// by their names alone, as `parameters.home`; `root` names the whole value.
///
/// # Errors
///
/// [`BundleError`] at the object that repeats a member, or when the text is
/// not JSON.
pub fn parse(text: &str, root: &str) -> Result<Value, BundleError> {
    let repeated = RefCell::new(None);
    let mut reader = serde_json::Deserializer::from_str(text);
    let parsed = Strict {
        at: None,
        root,
        repeated: &repeated,
    }
    .deserialize(&mut reader)
    .and_then(|value| reader.end().map(|()| value));
    if let Some(error) = repeated.into_inner() {
        return Err(error);
    }
    parsed.map_err(|e| BundleError {
        at: root.to_owned(),
        problem: format!("not JSON: {e}"),
    })
}

/// A value at a path, `None` for the whole value. A repeated member is
/// recorded in `repeated`, so that the caller reports it with its path, and
/// the parse stops.
struct Strict<'a> {
    at: Option<String>,
    root: &'a str,
    repeated: &'a RefCell<Option<BundleError>>,
}

impl Strict<'_> {
    fn path(&self) -> &str {
        self.at.as_deref().unwrap_or(self.root)
    }

    /// The value of a member: `.name` for a plain name, `["key"]` otherwise.
    fn member(&self, key: &str) -> Self {
        let plain = !key.is_empty() && key.bytes().all(|b| b.is_ascii_lowercase() || b == b'_');
        let at = match (&self.at, plain) {
            (None, true) => key.to_owned(),
            (Some(at), true) => format!("{at}.{key}"),
            (_, false) => format!("{}[{key:?}]", self.path()),
        };
        Self {
            at: Some(at),
            root: self.root,
            repeated: self.repeated,
        }
    }

    fn item(&self, index: usize) -> Self {
        Self {
            at: Some(format!("{}[{index}]", self.path())),
            root: self.root,
            repeated: self.repeated,
        }
    }
}

impl<'de> DeserializeSeed<'de> for Strict<'_> {
    type Value = Value;

    fn deserialize<D: de::Deserializer<'de>>(self, deserializer: D) -> Result<Value, D::Error> {
        deserializer.deserialize_any(self)
    }
}

impl<'de> Visitor<'de> for Strict<'_> {
    type Value = Value;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a JSON value")
    }

    fn visit_bool<E>(self, v: bool) -> Result<Value, E> {
        Ok(Value::Bool(v))
    }

    fn visit_i64<E>(self, v: i64) -> Result<Value, E> {
        Ok(Value::from(v))
    }

    fn visit_u64<E>(self, v: u64) -> Result<Value, E> {
        Ok(Value::from(v))
    }

    fn visit_f64<E>(self, v: f64) -> Result<Value, E> {
        Ok(Value::from(v))
    }

    fn visit_str<E>(self, v: &str) -> Result<Value, E> {
        Ok(Value::String(v.to_owned()))
    }

    fn visit_string<E>(self, v: String) -> Result<Value, E> {
        Ok(Value::String(v))
    }

    fn visit_unit<E>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Value, A::Error> {
        let mut items = Vec::new();
        while let Some(item) = seq.next_element_seed(self.item(items.len()))? {
            items.push(item);
        }
        Ok(Value::Array(items))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut members = Map::new();
        let mut seen = BTreeSet::new();
        while let Some(key) = map.next_key::<String>()? {
            if !seen.insert(key.clone()) {
                *self.repeated.borrow_mut() = Some(BundleError {
                    at: self.path().to_owned(),
                    problem: format!("gives the member {key:?} twice"),
                });
                return Err(de::Error::custom("a member is given twice"));
            }
            let value = map.next_value_seed(self.member(&key))?;
            members.insert(key, value);
        }
        Ok(Value::Object(members))
    }
}
