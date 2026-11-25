//! The shared rules' WebAssembly module, from the AnkiQuest-Server release
//! that `ankiquest-rules.json` pins (see `release`), written to
//! `addon/rules/ankiquest_rules.wasm` for the add-on's pages
//! (`addon/rules.py`). `ANKIQUEST_RULES_DIR` names a folder holding the
//! release assets to use instead of downloading them, for a release not
//! published yet.

use std::fs;
use std::path::Path;

use crate::release::{self, Source};

/// AnkiQuest-Server's rules releases and their pin.
const SOURCE: Source = Source {
    pin: "ankiquest-rules.json",
    repository: "AnkiQuest-Server rules",
    releases: "https://github.com/AnkiQuest/AnkiQuest-Server/releases/download",
    local_dir: "ANKIQUEST_RULES_DIR",
    cache_dir: "ANKIQUEST_RULES_CACHE",
    cache_name: "ankiquest-rules",
};

/// The release asset, and its name in the add-on.
const MODULE: &str = "ankiquest_rules.wasm";

/// The module's folder inside the add-on.
const FOLDER: &str = "rules";

/// The first bytes of every WebAssembly module: `\0asm` and version 1.
const WASM_HEADER: &[u8] = b"\0asm\x01\0\0\0";

/// Writes the pinned module into `addon`.
pub(super) fn fetch(repo: &Path, addon: &Path) -> Result<(), String> {
    let bytes = release::fetch(&SOURCE, repo, MODULE)?;
    stage(&bytes, addon)
}

/// Writes `bytes`, a WebAssembly module, to `addon/rules/`.
fn stage(bytes: &[u8], addon: &Path) -> Result<(), String> {
    if !bytes.starts_with(WASM_HEADER) {
        return Err(format!("{MODULE}: not a WebAssembly module"));
    }
    let folder = addon.join(FOLDER);
    fs::create_dir_all(&folder).map_err(|e| format!("{}: {e}", folder.display()))?;
    let path = folder.join(MODULE);
    fs::write(&path, bytes).map_err(|e| format!("{}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use tempfile::TempDir;

    use super::*;

    #[test]
    fn the_module_lands_in_the_rules_folder() {
        let addon = TempDir::new().unwrap();
        let module = [WASM_HEADER, b"rest"].concat();
        stage(&module, addon.path()).unwrap();
        let written = fs::read(addon.path().join("rules/ankiquest_rules.wasm")).unwrap();
        assert_eq!(module, written);
    }

    #[test]
    fn anything_else_is_refused() {
        let addon = TempDir::new().unwrap();
        let error = stage(b"<html>", addon.path()).unwrap_err();
        assert!(error.contains("not a WebAssembly module"), "{error}");
        assert!(!addon.path().join(FOLDER).exists());
    }
}
