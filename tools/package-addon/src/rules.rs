//! The shared rules, from the AnkiQuest-Server release that
//! `ankiquest-rules.json` pins (see `release`): the WebAssembly module,
//! written to `addon/rules/ankiquest_rules.wasm` for the add-on's pages
//! (`addon/rules.py`), and the UniFFI library of each desktop platform with
//! its Python bindings, written to `addon/rules/<platform>/` for rules
//! Python needs (`addon/native_rules.py`). `ANKIQUEST_RULES_DIR` names a
//! folder holding the release assets to use instead of downloading them,
//! for a release not published yet.

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

/// The Python bindings, one copy in each platform's folder next to its
/// library, which they load from their own folder.
const BINDINGS: &str = "ankiquest_rules.py";

/// A desktop library: its release asset, the platform folder it goes in and
/// the name the bindings load it by.
struct Library {
    asset: &'static str,
    platform: &'static str,
    name: &'static str,
}

/// Every platform the add-on ships a library for: those Anki 24.11 and newer
/// run on, as AnkiQuest-Server's rules release builds them.
const LIBRARIES: [Library; 5] = [
    Library {
        asset: "libankiquest_rules-linux-x86_64.so",
        platform: "linux-x86_64",
        name: "libankiquest_rules.so",
    },
    Library {
        asset: "libankiquest_rules-linux-aarch64.so",
        platform: "linux-aarch64",
        name: "libankiquest_rules.so",
    },
    Library {
        asset: "ankiquest_rules-windows-x86_64.dll",
        platform: "windows-x86_64",
        name: "ankiquest_rules.dll",
    },
    Library {
        asset: "libankiquest_rules-macos-arm64.dylib",
        platform: "macos-arm64",
        name: "libankiquest_rules.dylib",
    },
    Library {
        asset: "libankiquest_rules-macos-x86_64.dylib",
        platform: "macos-x86_64",
        name: "libankiquest_rules.dylib",
    },
];

/// Writes the pinned module, bindings and libraries into `addon`. Every
/// asset is fetched and checked before anything is written.
pub(super) fn fetch(repo: &Path, addon: &Path) -> Result<(), String> {
    let module = release::fetch(&SOURCE, repo, MODULE)?;
    let bindings = release::fetch(&SOURCE, repo, BINDINGS)?;
    let libraries = LIBRARIES
        .iter()
        .map(|library| release::fetch(&SOURCE, repo, library.asset))
        .collect::<Result<Vec<_>, String>>()?;
    stage(&module, addon)?;
    for (library, bytes) in LIBRARIES.iter().zip(&libraries) {
        native(library, bytes, &bindings, addon)?;
    }
    Ok(())
}

/// Writes one platform's library and a copy of the bindings to
/// `addon/rules/<platform>/`.
fn native(library: &Library, bytes: &[u8], bindings: &[u8], addon: &Path) -> Result<(), String> {
    let folder = addon.join(FOLDER).join(library.platform);
    fs::create_dir_all(&folder).map_err(|e| format!("{}: {e}", folder.display()))?;
    for (name, data) in [(library.name, bytes), (BINDINGS, bindings)] {
        let path = folder.join(name);
        fs::write(&path, data).map_err(|e| format!("{}: {e}", path.display()))?;
    }
    Ok(())
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
    fn each_platform_gets_its_library_and_the_bindings() {
        let addon = TempDir::new().unwrap();
        for library in &LIBRARIES {
            native(library, library.asset.as_bytes(), b"bindings", addon.path()).unwrap();
        }
        for library in &LIBRARIES {
            let folder = addon.path().join("rules").join(library.platform);
            let written = fs::read(folder.join(library.name)).unwrap();
            assert_eq!(library.asset.as_bytes(), written.as_slice());
            assert_eq!(
                b"bindings".to_vec(),
                fs::read(folder.join(BINDINGS)).unwrap()
            );
        }
    }

    #[test]
    fn anything_else_is_refused() {
        let addon = TempDir::new().unwrap();
        let error = stage(b"<html>", addon.path()).unwrap_err();
        assert!(error.contains("not a WebAssembly module"), "{error}");
        assert!(!addon.path().join(FOLDER).exists());
    }
}
