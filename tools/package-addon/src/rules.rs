//! The shared rules, from the newest AnkiQuest-Server `rules-<N>` release:
//! the WebAssembly module, written to `addon/rules/ankiquest_rules.wasm` for
//! the add-on's pages (`addon/rules.py`), and the UniFFI library of each
//! desktop platform with its Python bindings, written to
//! `addon/rules/<platform>/` for rules Python needs (`addon/native_rules.py`).
//!
//! The add-on uses server `master`, so it takes the newest release at build
//! time rather than pinning one: it lists the releases, takes the highest N,
//! checks each asset against that release's `SHA256SUMS` and records the tag
//! and hashes in `addon/rules/release.json`, so a build can be traced and
//! rebuilt. `ANKIQUEST_RULES_TAG` names a release to use instead, to rebuild
//! one; `ANKIQUEST_RULES_DIR` a folder with the assets and their `SHA256SUMS`,
//! for a release not published yet.

use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

use crate::release::{self, Source};

/// AnkiQuest-Server's rules releases. Assets are checked against the
/// release's `SHA256SUMS`, not a pin file.
const SOURCE: Source = Source {
    pin: SUMS,
    repository: "AnkiQuest-Server rules",
    releases: "https://github.com/AnkiQuest/AnkiQuest-Server/releases/download",
    local_dir: "ANKIQUEST_RULES_DIR",
    cache_dir: "ANKIQUEST_RULES_CACHE",
    cache_name: "ankiquest-rules",
};

/// AnkiQuest-Server's releases, newest first, as GitHub's API lists them.
const RELEASES_API: &str =
    "https://api.github.com/repos/AnkiQuest/AnkiQuest-Server/releases?per_page=100";

/// What every rules release tag starts with.
const TAG_PREFIX: &str = "rules-";

/// The variable naming a release to use instead of the newest.
const TAG_VAR: &str = "ANKIQUEST_RULES_TAG";

/// The tag recorded for assets from a local folder without `ANKIQUEST_RULES_TAG`.
const LOCAL_TAG: &str = "local";

/// Every release lists its assets' hashes here.
const SUMS: &str = "SHA256SUMS";

/// The release asset, and its name in the add-on.
const MODULE: &str = "ankiquest_rules.wasm";

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

/// The assets the add-on takes from a release.
const ASSETS: [&str; 7] = [
    MODULE,
    BINDINGS,
    LIBRARIES[0].asset,
    LIBRARIES[1].asset,
    LIBRARIES[2].asset,
    LIBRARIES[3].asset,
    LIBRARIES[4].asset,
];

/// The rules' folder inside the add-on.
const FOLDER: &str = "rules";

/// The record of the release a build took, inside the rules' folder.
const RECORD: &str = "release.json";

/// The first bytes of every WebAssembly module: `\0asm` and version 1.
const WASM_HEADER: &[u8] = b"\0asm\x01\0\0\0";

/// Writes the newest release's module, bindings and libraries into `addon`,
/// with the record of which release they came from. Every asset is fetched
/// and checked before anything is written.
pub(super) fn fetch(_repo: &Path, addon: &Path) -> Result<(), String> {
    let local = env::var_os(SOURCE.local_dir).map(PathBuf::from);
    let chosen = env::var(TAG_VAR).ok().filter(|tag| !tag.is_empty());
    let (tag, sums, assets) = match local {
        Some(folder) => local_assets(&folder, chosen)?,
        None => released_assets(chosen)?,
    };
    stage(&assets[MODULE], addon)?;
    for library in &LIBRARIES {
        native(library, &assets[library.asset], &assets[BINDINGS], addon)?;
    }
    record(&tag, &sums, addon)
}

/// The assets and hashes of release `chosen`, or of the newest one.
fn released_assets(chosen: Option<String>) -> Result<Release, String> {
    let tag = match chosen {
        Some(tag) => tag,
        None => newest(&String::from_utf8_lossy(&release::get(RELEASES_API)?))?
            .ok_or("AnkiQuest-Server has no rules-<N> release yet")?,
    };
    let url = format!("{}/{tag}/{SUMS}", SOURCE.releases);
    let sums = sums(&String::from_utf8_lossy(&release::get(&url)?))?;
    let mut assets = BTreeMap::new();
    for name in ASSETS {
        let hash = listed(&sums, name)?;
        assets.insert(name, release::checked(&SOURCE, &tag, name, hash)?);
    }
    Ok((tag, sums, assets))
}

/// The assets and hashes in a local folder, checked against its `SHA256SUMS`.
fn local_assets(folder: &Path, chosen: Option<String>) -> Result<Release, String> {
    let read = |name: &str| {
        let path = folder.join(name);
        fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))
    };
    let sums = sums(&String::from_utf8_lossy(&read(SUMS)?))?;
    let mut assets = BTreeMap::new();
    for name in ASSETS {
        let bytes = read(name)?;
        release::verify(&SOURCE, name, &bytes, listed(&sums, name)?)?;
        assets.insert(name, bytes);
    }
    Ok((chosen.unwrap_or_else(|| LOCAL_TAG.to_owned()), sums, assets))
}

/// A release's tag, its `SHA256SUMS` and the assets taken from it.
type Release = (
    String,
    BTreeMap<String, String>,
    BTreeMap<&'static str, Vec<u8>>,
);

/// The hash `SHA256SUMS` lists for `name`.
fn listed<'a>(sums: &'a BTreeMap<String, String>, name: &str) -> Result<&'a str, String> {
    sums.get(name)
        .map(String::as_str)
        .ok_or_else(|| format!("{SUMS} does not list {name}"))
}

/// The published `rules-<N>` release with the highest N in GitHub's
/// releases JSON; drafts, prereleases and other tags are skipped.
fn newest(json: &str) -> Result<Option<String>, String> {
    let releases: Vec<Value> = serde_json::from_str(json).map_err(|e| format!("releases: {e}"))?;
    let tags = releases.iter().filter(|release| {
        release["draft"] != Value::Bool(true) && release["prerelease"] != Value::Bool(true)
    });
    Ok(tags
        .filter_map(|release| release["tag_name"].as_str())
        .filter_map(|tag| number(tag).map(|n| (n, tag)))
        .max()
        .map(|(_, tag)| tag.to_owned()))
}

/// The N of a `rules-<N>` tag; None for anything else.
fn number(tag: &str) -> Option<u64> {
    let digits = tag.strip_prefix(TAG_PREFIX)?;
    if digits.is_empty() || digits.starts_with('0') || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

/// `SHA256SUMS` as asset name to hash: `<hash>  <name>` per line.
fn sums(text: &str) -> Result<BTreeMap<String, String>, String> {
    let mut found = BTreeMap::new();
    for line in text.lines().filter(|line| !line.trim().is_empty()) {
        let bad = || format!("{SUMS}: bad line {line:?}");
        let (hash, rest) = line.split_once(' ').ok_or_else(bad)?;
        let name = rest.strip_prefix([' ', '*']).unwrap_or_default();
        let hex = hash.len() == 64 && hash.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'));
        if !hex || name.is_empty() {
            return Err(bad());
        }
        found.insert(name.to_owned(), hash.to_owned());
    }
    Ok(found)
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

/// Writes `addon/rules/release.json`: the tag and the hashes of the assets
/// taken, so the build can be traced and rebuilt (`ANKIQUEST_RULES_TAG`).
fn record(tag: &str, sums: &BTreeMap<String, String>, addon: &Path) -> Result<(), String> {
    let assets: serde_json::Map<String, Value> = ASSETS
        .iter()
        .filter_map(|name| {
            sums.get(*name)
                .map(|hash| ((*name).to_owned(), json!(hash)))
        })
        .collect();
    let text = serde_json::to_string_pretty(&json!({"tag": tag, "assets": assets}))
        .map_err(|e| e.to_string())?;
    let path = addon.join(FOLDER).join(RECORD);
    fs::write(&path, format!("{text}\n")).map_err(|e| format!("{}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use sha2::{Digest, Sha256};
    use tempfile::TempDir;

    use super::*;

    fn hash(bytes: &[u8]) -> String {
        Sha256::digest(bytes)
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect()
    }

    #[test]
    fn the_newest_published_rules_release_wins() {
        let json = r#"[
            {"tag_name": "rules-9"}, {"tag_name": "rules-12", "draft": true},
            {"tag_name": "rules-10"}, {"tag_name": "rules-11", "prerelease": true},
            {"tag_name": "addon-40"}, {"tag_name": "rules-03"}
        ]"#;
        assert_eq!(Ok(Some("rules-10".to_owned())), newest(json));
        assert_eq!(Ok(None), newest(r#"[{"tag_name": "v1"}]"#));
        assert!(newest("not json").is_err());
    }

    #[test]
    fn sums_are_read_and_bad_lines_refused() {
        let line = format!("{}  {MODULE}\n", "a".repeat(64));
        assert_eq!("a".repeat(64), sums(&line).unwrap()[MODULE]);
        assert!(sums("abc  x\n").is_err());
    }

    #[test]
    fn a_local_folder_is_checked_and_recorded() {
        let folder = TempDir::new().unwrap();
        let module = [WASM_HEADER, b"rest"].concat();
        let mut listing = String::new();
        for name in ASSETS {
            let bytes = if name == MODULE {
                module.clone()
            } else {
                name.as_bytes().to_vec()
            };
            fs::write(folder.path().join(name), &bytes).unwrap();
            listing.push_str(&format!("{}  {name}\n", hash(&bytes)));
        }
        fs::write(folder.path().join(SUMS), listing).unwrap();
        let (tag, sums, assets) = local_assets(folder.path(), None).unwrap();
        assert_eq!(LOCAL_TAG, tag);
        assert_eq!(module, assets[MODULE]);

        let addon = TempDir::new().unwrap();
        stage(&assets[MODULE], addon.path()).unwrap();
        record("rules-4", &sums, addon.path()).unwrap();
        let written: Value =
            serde_json::from_slice(&fs::read(addon.path().join("rules/release.json")).unwrap())
                .unwrap();
        assert_eq!(json!("rules-4"), written["tag"]);
        assert_eq!(json!(hash(&module)), written["assets"][MODULE]);
        assert_eq!(ASSETS.len(), written["assets"].as_object().unwrap().len());

        // A module that does not match SHA256SUMS is refused.
        fs::write(folder.path().join(MODULE), b"other").unwrap();
        assert!(local_assets(folder.path(), None).is_err());
    }

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
