//! The manifest of companion art outside `static/` (`art-exports.json`).
//!
//! `exports` lists every committed copy of a master: the file, its master
//! and the SHA-256 the exporter wrote, so the tests can regenerate each
//! copy and compare. `retired` lists copies nothing reads any more, kept
//! because companion art is never deleted (AGENTS.md, Companion art).

use std::fs;

use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use super::root;

/// The manifest, relative to the repository root.
pub(super) const MANIFEST: &str = "crates/xtask/art-exports.json";

/// What the manifest says about its own format.
const ABOUT: &str = "Companion art outside static/<companion>/. `exports`: \
committed copies of a master, written by the named xtask exporter, with the SHA-256 \
of the file it wrote; the tests regenerate each copy and compare. `retired`: copies \
nothing reads any more, kept because companion art is never deleted. See \
docs/branding/mascot-source.md.";

/// One committed copy of a master.
pub(super) struct Export {
    pub(super) file: String,
    pub(super) master: String,
    pub(super) exporter: Exporter,
    pub(super) sha256: String,
}

/// The exporter that writes a copy.
#[derive(Clone, Copy, PartialEq, Debug)]
pub(super) enum Exporter {
    /// `export-addon-art`: 256 px palette PNGs.
    Addon,
    /// `export-addon-art`: small palette PNG icons.
    AddonIcon,
}

impl Exporter {
    fn name(self) -> &'static str {
        match self {
            Exporter::Addon => "addon",
            Exporter::AddonIcon => "addon_icon",
        }
    }

    fn parse(name: &str) -> Option<Exporter> {
        [Exporter::Addon, Exporter::AddonIcon]
            .into_iter()
            .find(|exporter| exporter.name() == name)
    }
}

/// A copy nothing reads any more, and why it is kept.
pub(super) struct Retired {
    pub(super) file: String,
    pub(super) why: String,
}

/// The whole manifest.
pub(super) struct Manifest {
    pub(super) exports: Vec<Export>,
    pub(super) retired: Vec<Retired>,
}

/// Reads the manifest.
pub(super) fn read() -> Result<Manifest, String> {
    let path = root().join(MANIFEST);
    let text = fs::read_to_string(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    let value: Value = serde_json::from_str(&text).map_err(|e| format!("{MANIFEST}: {e}"))?;
    let field = |entry: &Value, name: &str| {
        entry[name]
            .as_str()
            .map(String::from)
            .ok_or(format!("{MANIFEST}: an entry has no {name}"))
    };

    // Committed copies, each with its exporter.
    let mut exports = Vec::new();
    for entry in value["exports"].as_array().ok_or("no exports")? {
        let exporter = field(entry, "exporter")?;
        exports.push(Export {
            file: field(entry, "file")?,
            master: field(entry, "master")?,
            exporter: Exporter::parse(&exporter).ok_or(format!("no exporter {exporter}"))?,
            sha256: field(entry, "sha256")?,
        });
    }

    // Retired copies, each with its reason.
    let mut retired = Vec::new();
    for entry in value["retired"].as_array().ok_or("no retired list")? {
        retired.push(Retired {
            file: field(entry, "file")?,
            why: field(entry, "why")?,
        });
    }
    Ok(Manifest { exports, retired })
}

/// Writes the manifest back, in its committed format.
pub(super) fn write(manifest: &Manifest) -> Result<(), String> {
    let exports: Vec<Value> = manifest
        .exports
        .iter()
        .map(|export| {
            json!({
                "file": export.file,
                "master": export.master,
                "exporter": export.exporter.name(),
                "sha256": export.sha256,
            })
        })
        .collect();
    let retired: Vec<Value> = manifest
        .retired
        .iter()
        .map(|retired| json!({"file": retired.file, "why": retired.why}))
        .collect();
    let value = json!({"_about": ABOUT, "exports": exports, "retired": retired});
    let text = serde_json::to_string_pretty(&value).map_err(|e| e.to_string())? + "\n";
    let path = root().join(MANIFEST);
    fs::write(&path, text).map_err(|e| format!("{}: {e}", path.display()))
}

/// Lower-case hex SHA-256 of `bytes`.
pub(super) fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
