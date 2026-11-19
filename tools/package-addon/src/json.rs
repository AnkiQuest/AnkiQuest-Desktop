//! JSON objects written as Python's `json.dumps(value, indent=2)` writes them.
//!
//! serde_json's `Value` sorts object keys; Python keeps them in file order
//! and appends new ones, so the top-level object is kept as a list.

use std::fmt;

use serde::de::{Deserialize, Deserializer, MapAccess, Visitor};
use serde_json::Value;

/// A JSON object that keeps its keys in file order.
#[derive(Default)]
pub(super) struct Object(Vec<(String, Value)>);

impl Object {
    /// The value of `key`.
    pub(super) fn get(&self, key: &str) -> Option<&Value> {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }

    /// Replaces `key` in place, or appends it.
    pub(super) fn set(&mut self, key: &str, value: Value) {
        if let Some(entry) = self.0.iter_mut().find(|(k, _)| k == key) {
            entry.1 = value;
            return;
        }
        self.0.push((key.to_owned(), value));
    }

    /// The object indented by two spaces, non-ASCII escaped.
    pub(super) fn pretty(&self) -> String {
        if self.0.is_empty() {
            return "{}".to_owned();
        }

        // Nested values keep serde's layout, shifted one level in.
        let entries: Vec<String> = self
            .0
            .iter()
            .map(|(key, value)| {
                let value = serde_json::to_string_pretty(value).unwrap_or_default();
                format!(
                    "  {}: {}",
                    Value::String(key.clone()),
                    value.replace('\n', "\n  ")
                )
            })
            .collect();
        ascii(&format!("{{\n{}\n}}", entries.join(",\n")))
    }
}

/// Escapes what Python's `ensure_ascii` escapes and serde_json does not:
/// DEL and every non-ASCII character, as UTF-16 `\uXXXX` units.
fn ascii(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        if c < '\u{7f}' {
            out.push(c);
            continue;
        }
        let mut units = [0u16; 2];
        for unit in c.encode_utf16(&mut units) {
            out.push_str(&format!("\\u{unit:04x}"));
        }
    }
    out
}

/// Reads an object's entries in file order.
struct Entries;

impl<'de> Visitor<'de> for Entries {
    type Value = Object;

    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("a JSON object")
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Object, A::Error> {
        let mut object = Object::default();
        while let Some((key, value)) = map.next_entry::<String, Value>()? {
            object.set(&key, value);
        }
        Ok(object)
    }
}

impl<'de> Deserialize<'de> for Object {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_map(Entries)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn keys_keep_file_order() {
        let mut object: Object = serde_json::from_str(r#"{"b": 1, "a": 2}"#).unwrap();
        object.set("b", json!(3));
        object.set("c", json!([]));
        assert_eq!(
            "{\n  \"b\": 3,\n  \"a\": 2,\n  \"c\": []\n}",
            object.pretty()
        );
    }

    #[test]
    fn non_ascii_is_escaped() {
        let mut object = Object::default();
        object.set("name", json!("Aki \u{e9}\u{7f}\u{1f525}"));
        let expected = "{\n  \"name\": \"Aki \\u00e9\\u007f\\ud83d\\udd25\"\n}";
        assert_eq!(expected, object.pretty());
    }

    #[test]
    fn nested_values_are_indented() {
        let mut object = Object::default();
        object.set("list", json!(["x", {"k": [1]}]));
        let expected = "{\n  \"list\": [\n    \"x\",\n    {\n      \"k\": [\n        1\n      ]\n    }\n  ]\n}";
        assert_eq!(expected, object.pretty());
    }
}
